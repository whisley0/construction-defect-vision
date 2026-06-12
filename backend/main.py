"""FastAPI app for RFI upload and extraction crosscheck."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.dataset_routes import router as dataset_router
from backend.routes import router
from backend.test_data_routes import router as test_data_router

app = FastAPI(
    title="Construction Defect Vision — RFI Crosscheck",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(test_data_router)
app.include_router(dataset_router)


@app.get("/health")
def health():
    return {"status": "ok"}
