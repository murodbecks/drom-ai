import { useCallback, useEffect, useRef, useState } from "react";

const CANVAS_WIDTH = 960;
const CANVAS_HEIGHT = 540;
const MIN_BOX_SIZE = 14;
const LABEL_PADDING = 6;
const LABEL_HEIGHT = 22;
const MOVE_HANDLE_SIZE = 14;
const BOX_COLORS = ["#9ca3af", "#8b949e", "#7b848f", "#6b7280", "#5f6673", "#4b5563"];

function makeId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function normalizeRect(start, end) {
  const startX = clamp(start.x, 0, CANVAS_WIDTH);
  const startY = clamp(start.y, 0, CANVAS_HEIGHT);
  const endX = clamp(end.x, 0, CANVAS_WIDTH);
  const endY = clamp(end.y, 0, CANVAS_HEIGHT);

  const x = Math.min(startX, endX);
  const y = Math.min(startY, endY);
  const width = Math.abs(endX - startX);
  const height = Math.abs(endY - startY);

  return {
    x,
    y,
    width,
    height
  };
}

function pointInBox(point, box) {
  return (
    point.x >= box.x &&
    point.x <= box.x + box.width &&
    point.y >= box.y &&
    point.y <= box.y + box.height
  );
}

function pointInRect(point, rect) {
  return (
    point.x >= rect.x &&
    point.x <= rect.x + rect.width &&
    point.y >= rect.y &&
    point.y <= rect.y + rect.height
  );
}

function getBoxLabelText(box, index) {
  return box.label || `object-${index + 1}`;
}

function getBoxColor(index) {
  return BOX_COLORS[index % BOX_COLORS.length];
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function makeScribbleCanvas(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.floor(width));
  canvas.height = Math.max(1, Math.floor(height));
  return canvas;
}

function makeFileSafeLabel(label, fallback) {
  const base = String(label || "")
    .replace(/[\\/:*?"<>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return base || fallback;
}

function canvasToPngBlob(canvas) {
  const outputCanvas = document.createElement("canvas");
  outputCanvas.width = canvas.width;
  outputCanvas.height = canvas.height;
  const outputCtx = outputCanvas.getContext("2d");
  if (!outputCtx) {
    return Promise.reject(new Error("Could not create export canvas context."));
  }
  outputCtx.fillStyle = "#ffffff";
  outputCtx.fillRect(0, 0, outputCanvas.width, outputCanvas.height);
  outputCtx.drawImage(canvas, 0, 0);

  return new Promise((resolve, reject) => {
    outputCanvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("Could not encode PNG."));
        return;
      }
      resolve(blob);
    }, "image/png");
  });
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function loadImageFromSrc(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Could not load image source."));
    image.src = src;
  });
}

async function cropBoxToBlob(sourceCanvas, box) {
  const sx = clamp(Math.floor(box.x), 0, sourceCanvas.width - 1);
  const sy = clamp(Math.floor(box.y), 0, sourceCanvas.height - 1);
  const sw = clamp(Math.floor(box.width), 1, sourceCanvas.width - sx);
  const sh = clamp(Math.floor(box.height), 1, sourceCanvas.height - sy);

  const outputCanvas = document.createElement("canvas");
  outputCanvas.width = sw;
  outputCanvas.height = sh;

  const outputCtx = outputCanvas.getContext("2d");
  if (!outputCtx) {
    throw new Error("Could not create temporary canvas context.");
  }

  outputCtx.fillStyle = "#ffffff";
  outputCtx.fillRect(0, 0, sw, sh);
  outputCtx.drawImage(sourceCanvas, sx, sy, sw, sh, 0, 0, sw, sh);

  return new Promise((resolve, reject) => {
    outputCanvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("Could not encode cropped image."));
        return;
      }
      resolve(blob);
    }, "image/png");
  });
}

async function callScribbleTo3D({
  endpoint,
  imageBlob,
  box,
  label,
  globalPrompt
}) {
  if (!endpoint) {
    await wait(450);
    return {
      mode: "mock",
      boxId: box.id,
      label,
      blendFile: `${label || "asset"}-${box.id}.blend`
    };
  }

  const body = new FormData();
  body.append("image", imageBlob, `${label || "object"}.png`);
  body.append("label", label || "");
  body.append("globalPrompt", globalPrompt || "");
  body.append("box", JSON.stringify(box));

  const response = await fetch(endpoint, {
    method: "POST",
    body
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  return { mode: "non-json", message: "API responded with non-JSON body." };
}

export default function App() {
  const drawingCanvasRef = useRef(null);
  const overlayCanvasRef = useRef(null);
  const mediaInputRef = useRef(null);
  const boxScribbleMapRef = useRef(new Map());
  const historyPastRef = useRef([]);
  const historyFutureRef = useRef([]);
  const boxFieldHistoryRef = useRef(new Set());
  const startPointRef = useRef(null);
  const moveStateRef = useRef({ active: false, boxId: null, offsetX: 0, offsetY: 0 });
  const drawingStateRef = useRef({ active: false, last: null, boxId: null });

  const [screen, setScreen] = useState("landing");
  const [sceneImage, setSceneImage] = useState(null);
  const [sceneImageSrc, setSceneImageSrc] = useState("");
  const [mode, setMode] = useState("box");
  const [boxes, setBoxes] = useState([]);
  const [draftBox, setDraftBox] = useState(null);
  const [globalPrompt, setGlobalPrompt] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [isDraggingBox, setIsDraggingBox] = useState(false);
  const [runResults, setRunResults] = useState({});
  const [strokeColor, setStrokeColor] = useState("#111111");
  const [historyState, setHistoryState] = useState({ canUndo: false, canRedo: false });

  const apiEndpoint = import.meta.env.VITE_SCRIBBLE_API_URL || "";

  const syncHistoryState = useCallback(() => {
    setHistoryState({
      canUndo: historyPastRef.current.length > 0,
      canRedo: historyFutureRef.current.length > 0
    });
  }, []);

  const captureSnapshot = useCallback(() => {
    const scribbles = {};
    boxes.forEach((box) => {
      const scribbleCanvas = boxScribbleMapRef.current.get(box.id);
      scribbles[box.id] = scribbleCanvas ? scribbleCanvas.toDataURL("image/png") : null;
    });

    return {
      boxes: boxes.map((box) => ({ ...box })),
      mode,
      strokeColor,
      globalPrompt,
      sceneImageSrc,
      scribbles
    };
  }, [boxes, globalPrompt, mode, sceneImageSrc, strokeColor]);

  const restoreSnapshot = useCallback(async (snapshot) => {
    boxFieldHistoryRef.current.clear();
    const nextMap = new Map();
    for (const box of snapshot.boxes) {
      const scribbleCanvas = makeScribbleCanvas(box.width, box.height);
      const dataUrl = snapshot.scribbles[box.id];
      if (dataUrl) {
        const ctx = scribbleCanvas.getContext("2d");
        if (ctx) {
          try {
            const image = await loadImageFromSrc(dataUrl);
            ctx.drawImage(image, 0, 0, scribbleCanvas.width, scribbleCanvas.height);
          } catch {
            // Keep the canvas empty if stored scribble fails to decode.
          }
        }
      }
      nextMap.set(box.id, scribbleCanvas);
    }

    boxScribbleMapRef.current = nextMap;
    setBoxes(snapshot.boxes);
    setMode(snapshot.mode);
    setStrokeColor(snapshot.strokeColor);
    setGlobalPrompt(snapshot.globalPrompt);
    setDraftBox(null);
    setRunResults({});
    setIsDraggingBox(false);
    moveStateRef.current = { active: false, boxId: null, offsetX: 0, offsetY: 0 };
    drawingStateRef.current = { active: false, last: null, boxId: null };

    if (snapshot.sceneImageSrc) {
      try {
        const image = await loadImageFromSrc(snapshot.sceneImageSrc);
        setSceneImage(image);
      } catch {
        setSceneImage(null);
      }
    } else {
      setSceneImage(null);
    }
    setSceneImageSrc(snapshot.sceneImageSrc || "");
    setScreen("editor");
  }, []);

  const pushHistorySnapshot = useCallback(() => {
    historyPastRef.current.push(captureSnapshot());
    if (historyPastRef.current.length > 40) {
      historyPastRef.current.shift();
    }
    historyFutureRef.current = [];
    syncHistoryState();
  }, [captureSnapshot, syncHistoryState]);

  const clearHistory = useCallback(() => {
    historyPastRef.current = [];
    historyFutureRef.current = [];
    boxFieldHistoryRef.current.clear();
    syncHistoryState();
  }, [syncHistoryState]);

  const undo = useCallback(async () => {
    if (isRunning || historyPastRef.current.length === 0) {
      return;
    }
    const previousSnapshot = historyPastRef.current.pop();
    historyFutureRef.current.push(captureSnapshot());
    await restoreSnapshot(previousSnapshot);
    syncHistoryState();
  }, [captureSnapshot, isRunning, restoreSnapshot, syncHistoryState]);

  const redo = useCallback(async () => {
    if (isRunning || historyFutureRef.current.length === 0) {
      return;
    }
    const nextSnapshot = historyFutureRef.current.pop();
    historyPastRef.current.push(captureSnapshot());
    await restoreSnapshot(nextSnapshot);
    syncHistoryState();
  }, [captureSnapshot, isRunning, restoreSnapshot, syncHistoryState]);

  const getCanvasPoint = useCallback((event) => {
    const overlayCanvas = overlayCanvasRef.current;
    if (!overlayCanvas) {
      return null;
    }
    const rect = overlayCanvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * CANVAS_WIDTH;
    const y = ((event.clientY - rect.top) / rect.height) * CANVAS_HEIGHT;
    return {
      x: clamp(x, 0, CANVAS_WIDTH),
      y: clamp(y, 0, CANVAS_HEIGHT)
    };
  }, []);

  const getLabelRectForBox = useCallback((box, index) => {
    const overlayCanvas = overlayCanvasRef.current;
    if (!overlayCanvas) {
      return null;
    }
    const ctx = overlayCanvas.getContext("2d");
    if (!ctx) {
      return null;
    }
    ctx.font = "14px Avenir Next, Segoe UI, sans-serif";
    const text = getBoxLabelText(box, index);
    const width = Math.ceil(ctx.measureText(text).width + LABEL_PADDING * 2);
    return {
      x: box.x,
      y: Math.max(0, box.y - LABEL_HEIGHT),
      width,
      height: LABEL_HEIGHT
    };
  }, []);

  const getMoveHandleRectForBox = useCallback((box) => {
    const size = MOVE_HANDLE_SIZE;
    const x = clamp(box.x - size * 0.3, 0, CANVAS_WIDTH - size);
    const y = clamp(box.y - size * 0.3, 0, CANVAS_HEIGHT - size);
    return { x, y, width: size, height: size };
  }, []);

  const findHitTarget = useCallback(
    (point) => {
      for (let index = boxes.length - 1; index >= 0; index -= 1) {
        const box = boxes[index];
        const handleRect = getMoveHandleRectForBox(box);
        if (pointInRect(point, handleRect)) {
          return { box, target: "handle" };
        }
        const labelRect = getLabelRectForBox(box, index);
        if (labelRect && pointInRect(point, labelRect)) {
          return { box, target: "label" };
        }
        if (pointInBox(point, box)) {
          return { box, target: "box" };
        }
      }
      return { box: null, target: null };
    },
    [boxes, getLabelRectForBox, getMoveHandleRectForBox]
  );

  const drawOverlay = useCallback(() => {
    const canvas = overlayCanvasRef.current;
    if (!canvas) {
      return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    ctx.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    ctx.font = "14px Avenir Next, Segoe UI, sans-serif";
    ctx.textBaseline = "top";

    boxes.forEach((box, index) => {
      const color = getBoxColor(index);

      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.fillStyle = `${color}18`;
      ctx.strokeRect(box.x, box.y, box.width, box.height);
      ctx.fillRect(box.x, box.y, box.width, box.height);

      const text = getBoxLabelText(box, index);
      const textWidth = Math.ceil(ctx.measureText(text).width + LABEL_PADDING * 2);
      ctx.fillStyle = color;
      ctx.fillRect(box.x, Math.max(0, box.y - LABEL_HEIGHT), textWidth, LABEL_HEIGHT);
      ctx.fillStyle = "#ffffff";
      ctx.fillText(text, box.x + LABEL_PADDING, Math.max(0, box.y - LABEL_HEIGHT + 4));

      const handle = getMoveHandleRectForBox(box);
      ctx.fillStyle = "#f3f4f6";
      ctx.strokeStyle = "#2f3748";
      ctx.lineWidth = 1;
      ctx.fillRect(handle.x, handle.y, handle.width, handle.height);
      ctx.strokeRect(handle.x, handle.y, handle.width, handle.height);
      ctx.restore();
    });

    if (draftBox && mode === "box") {
      ctx.save();
      ctx.strokeStyle = "#ff9d00";
      ctx.lineWidth = 2;
      ctx.setLineDash([7, 4]);
      ctx.strokeRect(draftBox.x, draftBox.y, draftBox.width, draftBox.height);
      ctx.restore();
    }
  }, [boxes, draftBox, getMoveHandleRectForBox, mode]);

  const renderScene = useCallback(() => {
    const canvas = drawingCanvasRef.current;
    if (!canvas) {
      return;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    ctx.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    if (sceneImage) {
      ctx.drawImage(sceneImage, 0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    }

    boxes.forEach((box) => {
      const scribbleCanvas = boxScribbleMapRef.current.get(box.id);
      if (!scribbleCanvas) {
        return;
      }
      ctx.drawImage(
        scribbleCanvas,
        0,
        0,
        scribbleCanvas.width,
        scribbleCanvas.height,
        box.x,
        box.y,
        box.width,
        box.height
      );
    });
  }, [boxes, sceneImage]);

  const drawStrokeSegment = useCallback(
    (from, to, box) => {
      if (!box) {
        return;
      }
      const scribbleCanvas = boxScribbleMapRef.current.get(box.id);
      if (!scribbleCanvas) {
        return;
      }
      const ctx = scribbleCanvas.getContext("2d");
      if (!ctx) {
        return;
      }

      const scaleX = box.width > 0 ? scribbleCanvas.width / box.width : 1;
      const scaleY = box.height > 0 ? scribbleCanvas.height / box.height : 1;
      const fromX = clamp(from.x - box.x, 0, box.width) * scaleX;
      const fromY = clamp(from.y - box.y, 0, box.height) * scaleY;
      const toX = clamp(to.x - box.x, 0, box.width) * scaleX;
      const toY = clamp(to.y - box.y, 0, box.height) * scaleY;

      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 3;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(fromX, fromY);
      ctx.lineTo(toX, toY);
      ctx.stroke();

      renderScene();
    },
    [renderScene, strokeColor]
  );

  useEffect(() => {
    renderScene();
  }, [renderScene]);

  useEffect(() => {
    drawOverlay();
  }, [drawOverlay]);

  const handlePointerDown = useCallback(
    (event) => {
      event.preventDefault();
      const point = getCanvasPoint(event);
      if (!point) {
        return;
      }
      event.currentTarget.setPointerCapture(event.pointerId);

      if (mode === "box") {
        startPointRef.current = point;
        setDraftBox({ x: point.x, y: point.y, width: 0, height: 0 });
        return;
      }

      const { box: hitBox, target } = findHitTarget(point);

      if (hitBox && (target === "label" || target === "handle")) {
        pushHistorySnapshot();
        moveStateRef.current = {
          active: true,
          boxId: hitBox.id,
          offsetX: point.x - hitBox.x,
          offsetY: point.y - hitBox.y
        };
        setIsDraggingBox(true);
        drawingStateRef.current = { active: false, last: null, boxId: null };
        return;
      }

      if (mode === "move") {
        if (!hitBox) {
          moveStateRef.current = { active: false, boxId: null, offsetX: 0, offsetY: 0 };
          setIsDraggingBox(false);
          return;
        }

        pushHistorySnapshot();
        moveStateRef.current = {
          active: true,
          boxId: hitBox.id,
          offsetX: point.x - hitBox.x,
          offsetY: point.y - hitBox.y
        };
        setIsDraggingBox(true);
        return;
      }

      if (!hitBox) {
        drawingStateRef.current = { active: false, last: null, boxId: null };
        return;
      }

      pushHistorySnapshot();
      drawingStateRef.current = { active: true, last: point, boxId: hitBox.id };
      drawStrokeSegment(point, point, hitBox);
    },
    [drawStrokeSegment, findHitTarget, getCanvasPoint, mode, pushHistorySnapshot]
  );

  const handlePointerMove = useCallback(
    (event) => {
      const point = getCanvasPoint(event);
      if (!point) {
        return;
      }

      if (mode === "box" && startPointRef.current) {
        const nextDraft = normalizeRect(startPointRef.current, point);
        setDraftBox(nextDraft);
        return;
      }

      if (mode === "move" || moveStateRef.current.active) {
        const moveState = moveStateRef.current;
        if (!moveState.active || !moveState.boxId) {
          return;
        }
        const draggedBox = boxes.find((box) => box.id === moveState.boxId);
        if (!draggedBox) {
          return;
        }

        const nextX = clamp(point.x - moveState.offsetX, 0, CANVAS_WIDTH - draggedBox.width);
        const nextY = clamp(point.y - moveState.offsetY, 0, CANVAS_HEIGHT - draggedBox.height);

        setBoxes((prev) =>
          prev.map((box) => {
            if (box.id !== moveState.boxId) {
              return box;
            }
            return { ...box, x: nextX, y: nextY };
          })
        );
        return;
      }

      if (mode !== "scribble") {
        return;
      }

      const current = drawingStateRef.current;
      if (!current.active || !current.last || !current.boxId) {
        return;
      }

      const activeBox = boxes.find((box) => box.id === current.boxId);
      if (!activeBox) {
        return;
      }

      drawStrokeSegment(current.last, point, activeBox);
      drawingStateRef.current = { active: true, last: point, boxId: current.boxId };
    },
    [boxes, drawStrokeSegment, getCanvasPoint, mode]
  );

  const handlePointerUp = useCallback(
    (event) => {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }

      if (mode === "box" && draftBox) {
        if (draftBox.width >= MIN_BOX_SIZE && draftBox.height >= MIN_BOX_SIZE) {
          pushHistorySnapshot();
          const nextBox = {
            id: makeId(),
            x: draftBox.x,
            y: draftBox.y,
            width: draftBox.width,
            height: draftBox.height,
            label: `object ${boxes.length + 1}`
          };
          boxScribbleMapRef.current.set(
            nextBox.id,
            makeScribbleCanvas(nextBox.width, nextBox.height)
          );
          setBoxes((prev) => [...prev, nextBox]);
        }
      }

      startPointRef.current = null;
      setDraftBox(null);
      moveStateRef.current = { active: false, boxId: null, offsetX: 0, offsetY: 0 };
      setIsDraggingBox(false);
      drawingStateRef.current = { active: false, last: null, boxId: null };
    },
    [boxes.length, draftBox, mode, pushHistorySnapshot]
  );

  const clearScribbles = useCallback((recordHistory = true) => {
    if (recordHistory) {
      pushHistorySnapshot();
    }
    boxScribbleMapRef.current.forEach((scribbleCanvas) => {
      const ctx = scribbleCanvas.getContext("2d");
      if (!ctx) {
        return;
      }
      ctx.clearRect(0, 0, scribbleCanvas.width, scribbleCanvas.height);
    });
    renderScene();
    setRunResults({});
  }, [pushHistorySnapshot, renderScene]);

  const resetAll = useCallback(() => {
    clearScribbles(false);
    boxScribbleMapRef.current.clear();
    boxFieldHistoryRef.current.clear();
    setBoxes([]);
    setDraftBox(null);
    setMode("box");
    setGlobalPrompt("");
    setRunResults({});
    setStrokeColor("#111111");
    setSceneImage(null);
    setSceneImageSrc("");
    moveStateRef.current = { active: false, boxId: null, offsetX: 0, offsetY: 0 };
    setIsDraggingBox(false);
  }, [clearScribbles]);

  const openBlankEditor = useCallback(() => {
    clearHistory();
    resetAll();
    setScreen("editor");
  }, [clearHistory, resetAll]);

  const openMediaPicker = useCallback(() => {
    mediaInputRef.current?.click();
  }, []);

  const handleMediaSelected = useCallback(
    (event) => {
      const file = event.target.files?.[0];
      if (!file) {
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const nextSrc = String(reader.result || "");
        const img = new Image();
        img.onload = () => {
          if (screen === "editor") {
            pushHistorySnapshot();
          } else {
            clearHistory();
          }
          resetAll();
          setSceneImage(img);
          setSceneImageSrc(nextSrc);
          setScreen("editor");
        };
        img.src = nextSrc;
      };
      reader.readAsDataURL(file);
      event.target.value = "";
    },
    [clearHistory, pushHistorySnapshot, resetAll, screen]
  );

  const deleteBoxById = useCallback((boxId) => {
    const targetBoxId = boxId;
    if (!targetBoxId) {
      return;
    }
    pushHistorySnapshot();
    boxScribbleMapRef.current.delete(targetBoxId);
    setBoxes((prev) => prev.filter((box) => box.id !== targetBoxId));
    setRunResults((prev) => {
      const next = { ...prev };
      delete next[targetBoxId];
      return next;
    });
  }, [pushHistorySnapshot]);

  const updateBoxLabel = useCallback((id, value) => {
    setBoxes((prev) =>
      prev.map((box) => {
        if (box.id !== id) {
          return box;
        }
        return { ...box, label: value };
      })
    );
  }, []);

  const beginBoxFieldEdit = useCallback(
    (boxId, fieldName) => {
      const key = `${boxId}:${fieldName}`;
      if (boxFieldHistoryRef.current.has(key)) {
        return;
      }
      pushHistorySnapshot();
      boxFieldHistoryRef.current.add(key);
    },
    [pushHistorySnapshot]
  );

  const endBoxFieldEdit = useCallback((boxId, fieldName) => {
    boxFieldHistoryRef.current.delete(`${boxId}:${fieldName}`);
  }, []);

  const activateScribbleMode = useCallback(() => {
    setMode("scribble");
  }, []);

  const runPipeline = useCallback(async () => {
    if (boxes.length === 0 || isRunning) {
      return;
    }

    const initialStatuses = boxes.reduce((acc, box) => {
      acc[box.id] = { status: "queued", message: "Queued for export..." };
      return acc;
    }, {});
    setRunResults(initialStatuses);
    setIsRunning(true);

    for (const [index, box] of boxes.entries()) {
      setRunResults((prev) => ({
        ...prev,
        [box.id]: { status: "running", message: "Preparing PNG..." }
      }));

      try {
        const scribbleCanvas = boxScribbleMapRef.current.get(box.id);
        if (!scribbleCanvas) {
          throw new Error("No scribble data found for this box.");
        }

        const fallbackLabel = `box ${index + 1}`;
        const fileBaseName = makeFileSafeLabel(box.label, fallbackLabel);
        const fileName = `${fileBaseName}.png`;
        const pngBlob = await canvasToPngBlob(scribbleCanvas);
        downloadBlob(pngBlob, fileName);

        setRunResults((prev) => ({
          ...prev,
          [box.id]: {
            status: "done",
            message: `Saved: ${fileName}`
          }
        }));
      } catch (error) {
        setRunResults((prev) => ({
          ...prev,
          [box.id]: {
            status: "error",
            message: error instanceof Error ? error.message : "Unknown error"
          }
        }));
      }
    }

    setIsRunning(false);
  }, [boxes, isRunning]);

  if (screen === "landing") {
    return (
      <div className="landing-screen">
        <div className="mode-switch">
          <button type="button" className="active">
            Dröm AI
          </button>
        </div>

        <div className="welcome-shell">
          <div className="welcome-copy">
            <h1>Draw Sketch to Scene</h1>
            <p>
              Sketch object areas, annotate them, and generate scene-ready assets.
              Start from a blank canvas or upload an image.
            </p>
            <div className="welcome-actions">
              <button type="button" className="primary" onClick={openMediaPicker}>
                Upload Media
              </button>
              <button type="button" className="secondary" onClick={openBlankEditor}>
                Create blank
              </button>
            </div>
          </div>
          <div className="welcome-preview" aria-hidden>
            <div className="preview-chip">Canvas</div>
            <div className="preview-chip">Box Tool</div>
            <div className="preview-chip">Scribble</div>
          </div>
          <input
            ref={mediaInputRef}
            type="file"
            accept="image/*"
            onChange={handleMediaSelected}
            hidden
          />
        </div>
      </div>
    );
  }

  return (
    <div className="editor-screen">
      <header className="editor-header">
        <div className="mode-switch">
          <button type="button" className="active">
            Dröm AI
          </button>
        </div>
      </header>

      <section className="editor-canvas-shell">
        <div className="canvas-wrap">
          <canvas
            ref={drawingCanvasRef}
            className="canvas-layer drawing-layer"
            width={CANVAS_WIDTH}
            height={CANVAS_HEIGHT}
          />
          <canvas
            ref={overlayCanvasRef}
            className="canvas-layer overlay-layer"
            width={CANVAS_WIDTH}
            height={CANVAS_HEIGHT}
            style={{
              cursor: isDraggingBox ? "grabbing" : mode === "move" ? "grab" : "crosshair"
            }}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
          />
        </div>
      </section>

      <section className="box-list-panel">
        <div className="box-list-header">
          <h2>Boxes</h2>
          <span>{boxes.length} total</span>
        </div>
        {boxes.length === 0 ? (
          <p className="box-list-empty">Draw a box to create a label entry.</p>
        ) : (
          <div className="box-list">
            {boxes.map((box, index) => (
              <article key={box.id} className="box-list-item">
                <div className="box-list-item-top">
                  <div className="box-list-item-title">
                    <span
                      className="box-color-dot"
                      style={{ backgroundColor: getBoxColor(index) }}
                      aria-hidden
                    />
                    <strong>Box {index + 1}</strong>
                    <small>
                      {Math.round(box.x)}, {Math.round(box.y)} - {Math.round(box.width)}x
                      {Math.round(box.height)}
                    </small>
                  </div>
                  <button
                    type="button"
                    onClick={() => deleteBoxById(box.id)}
                    disabled={isRunning}
                    title="Delete this box"
                  >
                    Delete
                  </button>
                </div>
                <label className="box-field">
                  Label
                  <input
                    type="text"
                    value={box.label || ""}
                    onFocus={() => beginBoxFieldEdit(box.id, "label")}
                    onBlur={() => endBoxFieldEdit(box.id, "label")}
                    onChange={(event) => updateBoxLabel(box.id, event.target.value)}
                    placeholder="Describe object (used as file name)"
                    disabled={isRunning}
                  />
                </label>
              </article>
            ))}
          </div>
        )}
      </section>

      <footer className="editor-toolbar">
        <button
          type="button"
          onClick={() => setMode("box")}
          className={mode === "box" ? "active" : ""}
          disabled={isRunning}
        >
          Box
        </button>
        <button
          type="button"
          onClick={activateScribbleMode}
          className={mode === "scribble" ? "active" : ""}
          disabled={isRunning || boxes.length === 0}
          title={boxes.length === 0 ? "Create a box first, then scribble inside it." : undefined}
        >
          Scribble
        </button>
        <button
          type="button"
          onClick={() => setMode("move")}
          className={mode === "move" ? "active" : ""}
          disabled={isRunning || boxes.length === 0}
        >
          Move
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={undo}
          disabled={isRunning || !historyState.canUndo}
          aria-label="Undo"
          title="Undo"
        >
          <span aria-hidden>⟲</span>
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={redo}
          disabled={isRunning || !historyState.canRedo}
          aria-label="Redo"
          title="Redo"
        >
          <span aria-hidden>⟳</span>
        </button>
        <button type="button" onClick={openMediaPicker} disabled={isRunning}>
          Add Image
        </button>
        <label className="color-picker">
          Color
          <input
            type="color"
            value={strokeColor}
            onChange={(event) => setStrokeColor(event.target.value)}
            disabled={isRunning}
            title="Scribble color"
          />
        </label>
        <button
          type="button"
          className="generate-button"
          onClick={runPipeline}
          disabled={isRunning || boxes.length === 0}
          title={apiEndpoint || "Mock mode enabled"}
        >
          {isRunning ? (
            "Generating..."
          ) : (
            <>
              <span>Generate Image</span>
              <span className="generate-badge" aria-label="star rating two">
                <span aria-hidden>★</span>
                <span>2</span>
              </span>
            </>
          )}
        </button>
        <input
          ref={mediaInputRef}
          type="file"
          accept="image/*"
          onChange={handleMediaSelected}
          hidden
        />
      </footer>
    </div>
  );
}
