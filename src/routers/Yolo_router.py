"""
Router FastAPI para processamento de imagens e vídeos com YOLO.

Dependências:
    pip install fastapi uvicorn python-multipart ultralytics opencv-python-headless Pillow numpy

Uso:
    uvicorn main:app --reload
    (No main.py: app.include_router(router))
"""

import io
import time
import tempfile
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/avi", "video/quicktime", "video/x-matroska"}
MAX_IMAGE_SIZE_MB = 10
MAX_VIDEO_SIZE_MB = 100

# Cache simples de modelos em memória (evita recarregar a cada requisição)
_model_cache: dict[str, YOLO] = {}


def get_model(model_name: str) -> YOLO:
    """Carrega o modelo YOLO com cache em memória."""
    if model_name not in _model_cache:
        try:
            _model_cache[model_name] = YOLO(model_name)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erro ao carregar o modelo '{model_name}': {str(exc)}",
            )
    return _model_cache[model_name]


def serialize_results(results) -> list[dict]:
    """Converte os resultados do YOLO em estrutura JSON serializável."""
    detections = []
    for result in results:
        for box in result.boxes:
            detection = {
                "class_id": int(box.cls[0]),
                "class_name": result.names[int(box.cls[0])],
                "confidence": round(float(box.conf[0]), 4),
                "bbox": {
                    "x1": round(float(box.xyxy[0][0]), 2),
                    "y1": round(float(box.xyxy[0][1]), 2),
                    "x2": round(float(box.xyxy[0][2]), 2),
                    "y2": round(float(box.xyxy[0][3]), 2),
                },
                "bbox_normalized": {
                    "x": round(float(box.xywhn[0][0]), 4),
                    "y": round(float(box.xywhn[0][1]), 4),
                    "w": round(float(box.xywhn[0][2]), 4),
                    "h": round(float(box.xywhn[0][3]), 4),
                },
            }
            detections.append(detection)
    return detections


def draw_boxes_on_image(image_array: np.ndarray, results) -> np.ndarray:
    """Desenha bounding boxes na imagem para retorno visual."""
    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            confidence = float(box.conf[0])
            class_name = result.names[int(box.cls[0])]

            cv2.rectangle(image_array, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"{class_name} {confidence:.2f}"
            (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(image_array, (x1, y1 - text_h - 6), (x1 + text_w, y1), (0, 255, 0), -1)
            cv2.putText(
                image_array, label, (x1, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA,
            )
    return image_array


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/yolo", tags=["YOLO Detection"])


# ---------------------------------------------------------------------------
# POST /yolo/detect/image  — retorna JSON com as detecções
# ---------------------------------------------------------------------------

@router.post(
    "/detect/image",
    summary="Detecta objetos em uma imagem e retorna JSON",
    response_description="Lista de objetos detectados com classe, confiança e bounding box",
)
async def detect_image(
    file: UploadFile = File(..., description="Imagem (JPEG, PNG, WEBP ou BMP)"),
    model: str = Form(default="yolov8n.pt", description="Nome ou caminho do modelo YOLO"),
    confidence: float = Form(default=0.25, ge=0.01, le=1.0, description="Limiar mínimo de confiança"),
    iou: float = Form(default=0.45, ge=0.01, le=1.0, description="Limiar de IoU para NMS"),
):
    # Validação de tipo
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Tipo não suportado: {file.content_type}. Use: {ALLOWED_IMAGE_TYPES}",
        )

    # Lê e valida tamanho
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_IMAGE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Imagem muito grande ({size_mb:.1f} MB). Máximo: {MAX_IMAGE_SIZE_MB} MB",
        )

    # Converte para array numpy
    try:
        pil_image = Image.open(io.BytesIO(content)).convert("RGB")
        image_array = np.array(pil_image)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Não foi possível decodificar a imagem: {str(exc)}",
        )

    # Inferência YOLO
    yolo = get_model(model)
    start = time.perf_counter()
    results = yolo(image_array, conf=confidence, iou=iou, verbose=False)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

    detections = serialize_results(results)

    return JSONResponse(content={
        "success": True,
        "model": model,
        "inference_time_ms": elapsed_ms,
        "image": {
            "width": pil_image.width,
            "height": pil_image.height,
            "filename": file.filename,
        },
        "total_detections": len(detections),
        "detections": detections,
    })


# ---------------------------------------------------------------------------
# POST /yolo/detect/image/annotated  — retorna a imagem com boxes desenhadas
# ---------------------------------------------------------------------------

@router.post(
    "/detect/image/annotated",
    summary="Detecta objetos e retorna a imagem anotada (JPEG)",
    response_class=StreamingResponse,
)
async def detect_image_annotated(
    file: UploadFile = File(..., description="Imagem (JPEG, PNG, WEBP ou BMP)"),
    model: str = Form(default="yolov8n.pt"),
    confidence: float = Form(default=0.25, ge=0.01, le=1.0),
    iou: float = Form(default=0.45, ge=0.01, le=1.0),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail=f"Tipo não suportado: {file.content_type}")

    content = await file.read()
    try:
        pil_image = Image.open(io.BytesIO(content)).convert("RGB")
        image_array = np.array(pil_image)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Imagem inválida: {str(exc)}")

    yolo = get_model(model)
    results = yolo(image_array, conf=confidence, iou=iou, verbose=False)

    # Converte para BGR (OpenCV) → desenha → converte de volta para RGB
    bgr = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
    annotated = draw_boxes_on_image(bgr, results)
    rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)

    # Encode como JPEG
    _, buffer = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return StreamingResponse(
        io.BytesIO(buffer.tobytes()),
        media_type="image/jpeg",
        headers={"X-Total-Detections": str(len(serialize_results(results)))},
    )


# ---------------------------------------------------------------------------
# POST /yolo/detect/video  — processa vídeo frame a frame, retorna JSON
# ---------------------------------------------------------------------------

@router.post(
    "/detect/video",
    summary="Detecta objetos em um vídeo e retorna JSON com detecções por frame",
)
async def detect_video(
    file: UploadFile = File(..., description="Vídeo (MP4, AVI, MOV ou MKV)"),
    model: str = Form(default="yolov8n.pt"),
    confidence: float = Form(default=0.25, ge=0.01, le=1.0),
    iou: float = Form(default=0.45, ge=0.01, le=1.0),
    frame_skip: int = Form(default=1, ge=1, le=60, description="Processar 1 a cada N frames"),
    max_frames: Optional[int] = Form(default=None, description="Limitar número de frames processados"),
):
    if file.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(status_code=415, detail=f"Tipo não suportado: {file.content_type}")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_VIDEO_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"Vídeo muito grande ({size_mb:.1f} MB). Máximo: {MAX_VIDEO_SIZE_MB} MB",
        )

    yolo = get_model(model)

    # Salva em arquivo temporário (OpenCV exige arquivo em disco)
    with tempfile.NamedTemporaryFile(suffix=Path(file.filename).suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    cap = cv2.VideoCapture(tmp_path)
    if not cap.isOpened():
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Não foi possível abrir o vídeo.")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frames_result = []
    frame_index = 0
    processed = 0
    start = time.perf_counter()

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_index % frame_skip == 0:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = yolo(rgb_frame, conf=confidence, iou=iou, verbose=False)
            detections = serialize_results(results)

            frames_result.append({
                "frame_index": frame_index,
                "timestamp_s": round(frame_index / fps, 3) if fps > 0 else None,
                "total_detections": len(detections),
                "detections": detections,
            })
            processed += 1

        frame_index += 1
        if max_frames and processed >= max_frames:
            break

    cap.release()
    Path(tmp_path).unlink(missing_ok=True)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

    return JSONResponse(content={
        "success": True,
        "model": model,
        "inference_time_ms": elapsed_ms,
        "video": {
            "filename": file.filename,
            "fps": fps,
            "total_frames": total_frames,
            "width": width,
            "height": height,
            "size_mb": round(size_mb, 2),
        },
        "processing": {
            "frame_skip": frame_skip,
            "frames_processed": processed,
        },
        "frames": frames_result,
    })


# ---------------------------------------------------------------------------
# GET /yolo/models  — lista modelos disponíveis
# ---------------------------------------------------------------------------

AVAILABLE_MODELS = {
    "yolov8n.pt": "YOLOv8 Nano — mais rápido, menos preciso",
    "yolov8s.pt": "YOLOv8 Small",
    "yolov8m.pt": "YOLOv8 Medium",
    "yolov8l.pt": "YOLOv8 Large",
    "yolov8x.pt": "YOLOv8 XLarge — mais lento, mais preciso",
    "yolov8n-seg.pt": "YOLOv8 Nano Segmentação",
    "yolov8n-pose.pt": "YOLOv8 Nano Pose Estimation",
}


@router.get("/models", summary="Lista modelos YOLO disponíveis")
async def list_models():
    return {
        "available_models": AVAILABLE_MODELS,
        "loaded_in_cache": list(_model_cache.keys()),
    }


# ---------------------------------------------------------------------------
# GET /yolo/health  — health check
# ---------------------------------------------------------------------------

@router.get("/health", summary="Health check do serviço YOLO")
async def health():
    return {
        "status": "ok",
        "models_cached": len(_model_cache),
    }
