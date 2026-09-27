import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/basemap/esri": {
        target: "https://server.arcgisonline.com",
        changeOrigin: true,
        rewrite: (path) =>
          path.replace(/^\/basemap\/esri/, "/ArcGIS/rest/services/World_Imagery/MapServer/tile"),
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.js"],
    setupFiles: ["./src/test-setup.js"],
  },
});
