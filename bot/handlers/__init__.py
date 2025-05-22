from aiogram import Router

from .area import router as area_router
from .start import router as start_router
from .tile_calc import router as tile_calc_router

router = Router()
router.include_router(area_router)
router.include_router(start_router)
router.include_router(tile_calc_router)
