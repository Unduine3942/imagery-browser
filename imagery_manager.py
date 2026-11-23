from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from models import ImageryRecord


class ImageryManager:
    def __init__(self, records: list[ImageryRecord] | None = None) -> None:
        self._records: list[ImageryRecord] = list(records) if records else []

    def load(self, records: list[ImageryRecord]) -> None:
        self._records = list(records)

    def all_records(self) -> list[ImageryRecord]:
        return list(self._records)

    def all_sensor_platforms(self) -> list[str]:
        return sorted({r.sensor_platform for r in self._records if r.sensor_platform})

    def all_image_types(self) -> list[str]:
        return sorted({r.image_type for r in self._records if r.image_type})

    def all_image_categories(self) -> list[str]:
        return sorted({r.image_category for r in self._records if r.image_category})

    def max_file_size_mb(self) -> float:
        if not self._records:
            return 0.0
        return max(r.file_size_bytes for r in self._records) / (1024 * 1024)

    def search(self, filters: dict) -> list[ImageryRecord]:
        results = list(self._records)
        results = self._filter_dates(results, filters)
        results = self._filter_sensors(results, filters)
        results = self._filter_image_types(results, filters)
        results = self._filter_categories(results, filters)
        results = self._filter_scene_search(results, filters)
        results = self._filter_size(results, filters)
        return results

    def sort_records(
        self, records: list[ImageryRecord], sort_key: str, reverse: bool = False
    ) -> list[ImageryRecord]:
        def key_fn(r: ImageryRecord):
            if sort_key == "scene_name":
                return (r.scene_name or "").lower()
            if sort_key == "sensor_platform":
                return (r.sensor_platform or "").lower()
            if sort_key == "image_type":
                return (r.image_type or "").lower()
            if sort_key == "image_category":
                return (r.image_category or "").lower()
            if sort_key == "image_id":
                return (r.image_id or "").lower()
            if sort_key == "filename":
                return r.filename.lower()
            if sort_key == "location_x":
                return r.centroid_x if r.centroid_x is not None else float("inf")
            if sort_key == "location_y":
                return r.centroid_y if r.centroid_y is not None else float("inf")
            if sort_key == "acquisition_date":
                return r.acquisition_date or datetime.min
            if sort_key == "ingest_date":
                return r.ingest_date
            if sort_key == "file_size":
                return r.file_size_bytes
            return (r.scene_name or r.filename).lower()

        return sorted(records, key=key_fn, reverse=reverse)

    # -- private helpers --

    def _filter_dates(self, records: list[ImageryRecord], filters: dict) -> list[ImageryRecord]:
        date_range = filters.get("date_range", "Any Date")
        date_field = filters.get("date_field", "acquisition")

        if date_range == "Any Date":
            return records

        now = datetime.now()
        start: Optional[datetime] = None
        end: Optional[datetime] = None

        if date_range == "Last 30 Days":
            start = now - timedelta(days=30)
        elif date_range == "Last 90 Days":
            start = now - timedelta(days=90)
        elif date_range == "Last Year":
            start = now - timedelta(days=365)
        elif date_range == "Custom Range":
            start = filters.get("date_start")
            end = filters.get("date_end")

        out = []
        for r in records:
            dt = r.acquisition_date if date_field == "acquisition" else r.ingest_date
            if dt is None:
                continue
            if start and dt < start:
                continue
            if end and dt > end:
                continue
            out.append(r)
        return out

    def _filter_sensors(self, records: list[ImageryRecord], filters: dict) -> list[ImageryRecord]:
        selected: Optional[list[str]] = filters.get("sensors")
        if not selected:
            return records
        return [r for r in records if r.sensor_platform in selected]

    def _filter_image_types(self, records: list[ImageryRecord], filters: dict) -> list[ImageryRecord]:
        selected: Optional[list[str]] = filters.get("image_types")
        if not selected:
            return records
        return [r for r in records if r.image_type in selected]

    def _filter_categories(self, records: list[ImageryRecord], filters: dict) -> list[ImageryRecord]:
        selected: Optional[list[str]] = filters.get("categories")
        if not selected:
            return records
        return [r for r in records if r.image_category in selected]

    def _filter_scene_search(self, records: list[ImageryRecord], filters: dict) -> list[ImageryRecord]:
        query = (filters.get("scene_search") or "").strip().upper()
        if not query:
            return records
        return [r for r in records if r.scene_name and query in r.scene_name.upper()]

    def _filter_size(self, records: list[ImageryRecord], filters: dict) -> list[ImageryRecord]:
        min_mb = filters.get("min_size_mb", 0.0)
        if min_mb <= 0:
            return records
        threshold = min_mb * 1024 * 1024
        return [r for r in records if r.file_size_bytes >= threshold]
