Sure 👍 Below is a **clean, complete, copy-paste ready `README.md`** for your GitHub repository.
I’ve **fixed formatting**, **improved clarity**, and **kept everything aligned with an FYP at UPM** and a **Chrome Extension–based system**, without inventing features or code.

You can **copy everything below directly into `README.md`**.

---

````markdown
# 🎓 Classync: Smart Monitoring & Presence Detection System

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Flask](https://img.shields.io/badge/Backend-Flask-green)
![Extension](https://img.shields.io/badge/Frontend-Chrome_Extension-orange)
![AI](https://img.shields.io/badge/AI-ArcFace_%26_YOLOv8-red)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

**Classync** is an intelligent classroom monitoring and attendance automation system developed as a **Final Year Project (FYP)** at **Universiti Putra Malaysia (UPM)**.

The system bridges the gap between physical classrooms and digital academic management by leveraging **Computer Vision** and **Artificial Intelligence** to automate attendance and analyze student presence in real time.

---

## 🚀 Key Features

- 🤖 **Smart Attendance**
  - Automatic attendance marking using **Face Recognition (ArcFace / InsightFace)**.

- ⚡ **Optimized Performance**
  - ArcFace models optimized using **ONNX Runtime (Opset 11)** for fast inference on standard laptops.

- 👀 **Classroom & Behavior Analysis**
  - Uses **YOLOv8 (Segmentation & Classification)** to analyze classroom environment and student focus.

- 🔌 **Chrome Extension Interface**
  - Lightweight browser-based interface for lecturers to start and manage sessions without installing extra software.

- ☁️ **Real-time Data Synchronization**
  - Attendance and session data are synced instantly using **Supabase**.

---

## 🛠️ Tech Stack

| Component | Technology | Description |
|--------|------------|-------------|
| Backend | Python (Flask) | REST API for video processing and database operations |
| AI Models | ArcFace (InsightFace) | High-accuracy face recognition |
| AI Models | YOLOv8 | Object detection, segmentation & classification |
| Frontend | JavaScript / HTML / CSS | Chrome Extension interface |
| Database | Supabase | Real-time cloud database |
| Computer Vision | OpenCV | Frame capture and image processing |

---

## 📸 Screenshots

![System Interface](https://via.placeholder.com/800x400?text=Upload+Your+Screenshot+Here)

> *Classync Chrome Extension interface during a live classroom session.*

---

## 📂 Project Structure

```text
Classync/
├── server/                  # Flask Backend
│   ├── app.py               # Main application entry
│   ├── models/              # AI model logic
│   ├── yolov8n-cls.pt       # YOLOv8 Classification model
│   ├── yolov8n-seg.pt       # YOLOv8 Segmentation model
│   └── requirements.txt     # Python dependencies
│
├── client/                  # Chrome Extension
│   ├── manifest.json        # Extension configuration
│   ├── popup.html           # UI layout
│   └── scripts/             # JavaScript logic
│
└── README.md
````

---

## ⚙️ Installation & Setup

Follow the steps below to run the project locally.

---

### ✅ Prerequisites

* Python **3.8 or higher**
* Google Chrome Browser
* Git
* **Git LFS** (required for large AI model files)

---

### 1️⃣ Clone the Repository

This project uses **Git LFS** for AI models.

```bash
git clone https://github.com/hannbella18/Classync.git
cd Classync
git lfs pull
```

---

### 2️⃣ Backend Setup (Flask Server)

Navigate to the backend folder and install dependencies:

```bash
cd server
pip install -r requirements.txt
```

#### 🔐 Environment Variables

Create a `.env` file inside the `server` folder:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
```

Run the Flask server:

```bash
python app.py
```

The server will run at:

```
http://127.0.0.1:5000
```

---

### 3️⃣ Frontend Setup (Chrome Extension)

1. Open **Google Chrome**
2. Go to:

   ```
   chrome://extensions/
   ```
3. Enable **Developer mode** (top right)
4. Click **Load unpacked**
5. Select the `client/` folder
6. Pin the **Classync** extension to the toolbar

---

## 🧠 AI Model Details

This system adopts a **hybrid AI approach**:

### 🔹 Face Recognition

* Initially experimented with MediaPipe
* Migrated to **ArcFace (InsightFace)** for:

  * Higher accuracy
  * Better performance under varying lighting conditions

### 🔹 Classroom Analysis

* **YOLOv8 Segmentation**

  * Understands classroom layout
* **YOLOv8 Classification**

  * Helps infer student presence and behavior

### 🔹 Optimization

* Models converted to **ONNX format**
* Reduced latency for real-time classroom use

---

## 👤 Author

**Hannbella**
Computer Science Student
Universiti Putra Malaysia (UPM)

* 🔗 GitHub: [https://github.com/hannbella18](https://github.com/hannbella18)
* 📧 Email: *(add your email here)*

---

## 📄 License

This project is licensed under the **MIT License**.
Feel free to use and modify for academic purposes.

```

---

If you want next:
- ✨ **More “FYP-style” academic wording**
- 📊 **Add system architecture diagram section**
- 🧪 **Add evaluation & results section**
- 🧠 **Add future work & limitations**

Just tell me which one 👍
```
