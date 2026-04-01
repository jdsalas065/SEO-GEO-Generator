"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI

from app.routers import articles, export, jobs

app = FastAPI(
    title="SEO-GEO Generator",
    description="Vietnamese content generation pipeline with SEO and GEO optimisation.",
    version="1.0.0",
)

app.include_router(jobs.router)
app.include_router(articles.router)
app.include_router(export.router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
