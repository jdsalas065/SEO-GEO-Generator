"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import articles, export, jobs

app = FastAPI(
    title="SEO-GEO Generator",
    description="Vietnamese content generation pipeline with SEO and GEO optimisation.",
    version="1.0.0",
)

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(articles.router)
app.include_router(export.router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
