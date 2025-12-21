// config.js - base URL for Classync backend production
const DEFAULT_API = "https://hannbella-classync.hf.space";

// Force API_BASE to use the production URL
const API_BASE = DEFAULT_API.trim().replace(/\/+$/, "");

// Expose for background.js
self.API_BASE = API_BASE;