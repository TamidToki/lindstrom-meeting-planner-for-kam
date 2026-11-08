import { mergeDataset, sampleDataset, type Dataset } from "./data";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("kam-private-data", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("datasets");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function readLocalDataset(): Promise<Dataset | undefined> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction("datasets", "readonly");
    const store = transaction.objectStore("datasets");
    const request = store.get("active");
    request.onsuccess = () => {
      if (request.result) { resolve(request.result); return; }
      const legacy = store.get("imports");
      legacy.onsuccess = () => resolve(legacy.result ? mergeDataset(sampleDataset, legacy.result) : undefined);
      legacy.onerror = () => reject(legacy.error);
    };
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => db.close();
  });
}

export async function clearLocalDataset(): Promise<void> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction("datasets", "readwrite");
    transaction.objectStore("datasets").delete("imports");
    transaction.oncomplete = () => { db.close(); resolve(); };
    transaction.onerror = () => { db.close(); reject(transaction.error); };
  });
}

export async function saveLocalDataset(data: Dataset, preservePrevious = false): Promise<void> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction("datasets", "readwrite");
    const store = transaction.objectStore("datasets");
    if (preservePrevious) {
      // A new session must not destroy work saved by a previous session.
      const previous = store.get("active");
      previous.onsuccess = () => {
        if (previous.result) store.put(previous.result, `archive:${crypto.randomUUID()}`);
        store.put(data, "active");
      };
    } else store.put(data, "active");
    transaction.oncomplete = () => { db.close(); resolve(); };
    transaction.onerror = () => { db.close(); reject(transaction.error); };
  });
}