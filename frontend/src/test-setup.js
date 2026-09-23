class MemoryStorage {
  constructor() {
    this.map = new Map();
  }
  clear() {
    this.map.clear();
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  setItem(key, value) {
    this.map.set(String(key), String(value));
  }
  removeItem(key) {
    this.map.delete(key);
  }
}

if (typeof globalThis.localStorage === "undefined" || !globalThis.localStorage) {
  globalThis.localStorage = new MemoryStorage();
}
if (typeof globalThis.sessionStorage === "undefined" || !globalThis.sessionStorage) {
  globalThis.sessionStorage = new MemoryStorage();
}
