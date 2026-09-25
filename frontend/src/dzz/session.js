import { dzzStatus } from "../api/dzz.js";
import { dzzSession } from "./urls.js";

let restorePromise = null;

export async function restoreDzzSession() {
  if (restorePromise) return restorePromise;
  restorePromise = (async () => {
    try {
      const status = await dzzStatus();
      if (status?.connected) {
        dzzSession.connected = true;
        if (status.service_url || status.url) {
          dzzSession.serviceRoot = status.service_url || status.url;
          dzzSession.url = status.service_url || status.url;
        }
        return true;
      }
      dzzSession.connected = false;
      return false;
    } catch {
      return false;
    } finally {
      restorePromise = null;
    }
  })();
  return restorePromise;
}
