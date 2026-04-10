"""
DwellSense Backend — FastAPI application entry point.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # Must happen before any service imports that read os.getenv()

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from routers import health, scan, pdf
from jobs.daily_refresh import run_all as daily_refresh
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dwellsense")

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schedule daily NYC data refresh at 3:00 AM
    scheduler.add_job(daily_refresh, "cron", hour=3, minute=0, id="daily_refresh")
    scheduler.start()
    logger.info("Daily refresh scheduler started — runs every day at 3:00 AM.")
    yield
    scheduler.shutdown()


app = FastAPI(
    title="DwellSense API",
    description="Real estate forensics backend — AI-powered threat analysis for any NYC address.",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow requests from the Next.js frontend
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(scan.router)
app.include_router(pdf.router)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
