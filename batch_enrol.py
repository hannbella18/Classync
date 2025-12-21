import os, glob, json, sys, uuid, argparse
import numpy as np
import cv2

# ---------- Embedder selection (uses your repo first) ----------
def _import_embedder():
    try:
        from vision.auto_enrol import face_embedding_bgr
        print("[batch] Using vision.auto_enrol.face_embedding_bgr")
        return face_embedding_bgr
    except Exception:
        pass
    try:
        from vision.auto_enrol import EmbedFactory
        ef = EmbedFactory()
        def _factory(img_bgr): return ef.embed_bgr(img_bgr)
        print("[batch] Using vision.auto_enrol.EmbedFactory")
        return _factory
    except Exception:
        pass
    try:
        import face_recognition
        def _fr_backend(img_bgr):
            rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            boxes = face_recognition.face_locations(rgb, model="hog")
            if not boxes: return None
            encs = face_recognition.face_encodings(rgb, boxes)
            return encs[0] if encs else None
        print("[batch] Using face_recognition fallback")
        return _fr_backend
    except Exception:
        print("[batch] ERROR: no embedding backend available.", file=sys.stderr)
        sys.exit(1)

EMBED = _import_embedder()

def _l2(v): 
    n = np.linalg.norm(v) + 1e-9
    return v / n

def _embed(img):
    try:
        emb = EMBED(img)
        if emb is None: return None
        return _l2(np.array(emb, dtype=np.float32))
    except Exception:
        return None

def _avg(embs):
    return _l2(np.mean(np.stack(embs), axis=0)) if len(embs) > 1 else embs[0]

def _load_gallery(path):
    if not os.path.exists(path): return {"students": []}
    with open(path, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return {"students": []}

def _save_gallery(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def _upsert(gal, name, emb):
    entry = next((s for s in gal["students"] if s.get("name") == name), None)
    if entry is None:
        gal["students"].append({
            "name": name,
            "emb": emb.tolist(),
            "id": str(uuid.uuid4())
        })
        print(f"[batch] Added {name}")
    else:
        entry["emb"] = emb.tolist()
        print(f"[batch] Updated {name}")

def main():
    parser = argparse.ArgumentParser(description="Batch enrol faces into gallery.json")
    # Defaults wired for Option A
    parser.add_argument("--root", default="vision/data/dataset",
                        help="Root folder containing subfolders per student (default: vision/data/dataset)")
    parser.add_argument("--out", default="vision/data/gallery.json",
                        help="Gallery output JSON (default: vision/data/gallery.json)")
    parser.add_argument("--update-only", action="store_true",
                        help="Only update existing students; skip adding new names")
    args = parser.parse_args()

    root = args.root
    out_path = args.out

    if not os.path.isdir(root):
        print(f"[batch] ERROR: dataset root not found: {root}", file=sys.stderr)
        sys.exit(1)

    gal = _load_gallery(out_path)

    # loop each student folder (subdir name becomes student 'name')
    for student_name in sorted(os.listdir(root)):
        folder = os.path.join(root, student_name)
        if not os.path.isdir(folder): 
            continue

        if args.update_only:
            exists = any(s.get("name") == student_name for s in gal["students"])
            if not exists:
                print(f"[batch] Skipping new student (update-only): {student_name}")
                continue

        # collect images
        patterns = ["*.jpg", "*.jpeg", "*.png", "*.bmp"]
        paths = []
        for pat in patterns:
            paths += glob.glob(os.path.join(folder, pat))
        if not paths:
            print(f"[batch] WARN: No images for {student_name}, skipping.")
            continue

        embs = []
        for p in paths:
            img = cv2.imread(p, cv2.IMREAD_COLOR)
            if img is None:
                print(f"[batch] WARN: unreadable image: {p}")
                continue
            emb = _embed(img)
            if emb is not None:
                embs.append(emb)

        if not embs:
            print(f"[batch] WARN: No embeddings for {student_name}, skipping.")
            continue

        avg = _avg(embs)
        _upsert(gal, student_name, avg)

    _save_gallery(out_path, gal)
    print(f"[batch] Done. Wrote {out_path}")

if __name__ == "__main__":
    main()
