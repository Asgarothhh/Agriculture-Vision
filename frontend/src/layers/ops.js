// Server-backed edits with undo/redo, shared by the map tools and the layers panel.
// A deleted and restored object/layer/folder gets a new server id; aliasId() records it
// so later undo steps resolve the new id.
import * as layersApi from "../api/layers.js";
import { pushUndo } from "../map/undo.js";
import {
  aliasId,
  createObjectOnServer,
  deleteFolderOnServer,
  deleteLayerOnServer,
  deleteObjectOnServer,
  getFolder,
  getLayer,
  loadMapData,
  mergeObjectsOnServer,
  moveToFolderOnServer,
  patchFolderOnServer,
  patchObjectOnServer,
  recordsOfLayer,
  refreshModel,
  resolveId,
  getLayers,
  allObjectRecords,
} from "./store.js";

/** Everything needed to recreate an object: layer, name, geometry, origin, crop, folder. */
export function snapshotRecord(record) {
  return {
    id: record.obj.id,
    layerId: record.layer.id,
    payload: { name: record.obj.name || "", geom: record.obj.geom, origin: record.obj.origin || "manual" },
    crop: record.obj.crop || null,
    folderId: record.obj.folder_id || null,
  };
}

export async function restoreSnapshot(item) {
  const current = resolveId(item.id);
  let again = await createObjectOnServer(resolveId(item.layerId), item.payload);
  aliasId(current, again.id);
  if (item.crop) again = await patchObjectOnServer(again.id, { crop: item.crop });
  if (item.folderId) {
    await moveToFolderOnServer({ objectId: again.id, folderId: resolveId(item.folderId) }).catch(() => {});
  }
  return again;
}

export async function createTracked(layerId, geom, name = "") {
  const created = await createObjectOnServer(layerId, { name, geom, origin: "manual" });
  const handle = { id: created.id, layerId, payload: { name: created.name || name, geom, origin: "manual" } };
  pushUndo({
    undo: async () => deleteObjectOnServer(resolveId(handle.id)),
    redo: async () => {
      const current = resolveId(handle.id);
      const again = await createObjectOnServer(resolveId(handle.layerId), handle.payload);
      aliasId(current, again.id);
    },
  });
  return created;
}

export async function patchTracked(id, before, after) {
  const updated = await patchObjectOnServer(id, { geom: after });
  pushUndo({
    undo: async () => patchObjectOnServer(resolveId(id), { geom: before }),
    redo: async () => patchObjectOnServer(resolveId(id), { geom: after }),
  });
  return updated;
}

export async function deleteTracked(records) {
  const done = [];
  try {
    for (const record of records) {
      const item = snapshotRecord(record);
      await deleteObjectOnServer(record.obj.id);
      done.push(item);
    }
  } finally {
    if (done.length) {
      pushUndo({
        undo: async () => {
          for (const item of done) await restoreSnapshot(item);
        },
        redo: async () => {
          for (const item of done) await deleteObjectOnServer(resolveId(item.id));
        },
      });
    }
  }
  return done.length;
}

/** The server keeps the first object with the new geometry and deletes the second. */
export async function mergeTracked(keepRecord, dropRecord, geom) {
  const keepId = keepRecord.obj.id;
  const keepBefore = keepRecord.obj.geom;
  const dropped = snapshotRecord(dropRecord);
  const merged = await mergeObjectsOnServer([keepId, dropRecord.obj.id], geom);
  pushUndo({
    undo: async () => {
      await patchObjectOnServer(resolveId(keepId), { geom: keepBefore });
      await restoreSnapshot(dropped);
    },
    redo: async () => mergeObjectsOnServer([resolveId(keepId), resolveId(dropped.id)], geom),
  });
  return merged;
}

export async function moveTracked(id, fromLayerId, toLayerId) {
  const updated = await patchObjectOnServer(id, { layer_id: toLayerId });
  pushUndo({
    undo: async () => patchObjectOnServer(resolveId(id), { layer_id: resolveId(fromLayerId) }),
    redo: async () => patchObjectOnServer(resolveId(id), { layer_id: resolveId(toLayerId) }),
  });
  return updated;
}

/** Deletes a user layer with its objects; undo recreates the layer and every object. */
export async function deleteLayerTracked(layerId) {
  const layer = getLayer(layerId);
  if (!layer) return;
  const saved = {
    id: layer.id,
    name: layer.name,
    color: layer.color,
    folderId: layer.folder_id || null,
    visible: layer.is_visible !== false,
    objects: recordsOfLayer(layerId).map(snapshotRecord),
  };
  await deleteLayerOnServer(layerId);
  pushUndo({
    undo: async () => {
      const current = resolveId(saved.id);
      const created = await layersApi.createLayer({ name: saved.name, color: saved.color });
      aliasId(current, created.id);
      const patch = {};
      if (saved.folderId) patch.folder_id = resolveId(saved.folderId);
      if (!saved.visible) patch.is_visible = false;
      if (Object.keys(patch).length) await layersApi.patchLayer(created.id, patch).catch(() => {});
      await loadMapData();
      for (const item of saved.objects) await restoreSnapshot(item);
    },
    redo: async () => deleteLayerOnServer(resolveId(saved.id)),
  });
}

/** Deletes a folder (its layers and objects stay); undo recreates it and puts them back. */
export async function deleteFolderTracked(folderId) {
  const folder = getFolder(folderId);
  if (!folder) return;
  const saved = {
    id: folder.id,
    name: folder.name,
    visible: folder.is_visible !== false,
    layerIds: getLayers().filter((l) => l.folder_id === folderId).map((l) => l.id),
    objectIds: allObjectRecords().filter((r) => r.obj.folder_id === folderId).map((r) => r.obj.id),
  };
  await deleteFolderOnServer(folderId);
  pushUndo({
    undo: async () => {
      const current = resolveId(saved.id);
      const created = await layersApi.createFolder(saved.name);
      aliasId(current, created.id);
      if (!saved.visible) await layersApi.patchFolder(created.id, { is_visible: false }).catch(() => {});
      for (const id of saved.layerIds) {
        await layersApi.moveFolderItem(created.id, { layer_id: resolveId(id) }).catch(() => {});
      }
      for (const id of saved.objectIds) {
        await layersApi.moveFolderItem(created.id, { object_id: resolveId(id) }).catch(() => {});
      }
      await loadMapData();
    },
    redo: async () => deleteFolderOnServer(resolveId(saved.id)),
  });
}

/** Folder visibility also switches the layers that live in it (reference toggleFolderVisibility). */
export async function setFolderVisibility(folderId, visible) {
  await patchFolderOnServer(folderId, { is_visible: visible });
  for (const layer of getLayers().filter((l) => l.folder_id === folderId)) {
    if ((layer.is_visible !== false) !== visible) {
      await layersApi.patchLayer(layer.id, { is_visible: visible });
      layer.is_visible = visible;
    }
  }
  refreshModel();
}
