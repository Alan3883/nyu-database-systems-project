"""Mappings for the data-lake catalogue and the ML governance tables.

Lineage chain represented here:

    DATASET -> DATA_ASSET -> DOCUMENT_CHUNK -> ML_CLUSTER_RESULT
            -> ML_RUN     -> ML_CLUSTER_SUMMARY
                          -> ML_CLUSTER_INDICATOR_MAP -> HEALTH_INDICATOR

DATA_ASSET rows are versioned rather than updated. When the monitor sees a
new checksum it inserts a new row and marks the previous one Superseded, so
every model run can still name the exact bytes it was trained on.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import FetchedValue
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Dataset(Base):
    __tablename__ = "dataset"

    dataset_id: Mapped[str] = mapped_column("datasetid", String(10), primary_key=True)
    dataset_name: Mapped[str] = mapped_column("datasetname", String(200))
    source_organization: Mapped[str] = mapped_column("sourceorganization", String(200))
    source_url: Mapped[str | None] = mapped_column("sourceurl", String(500))
    data_classification: Mapped[str | None] = mapped_column("dataclassification", String(50))
    geographic_level: Mapped[str | None] = mapped_column("geographiclevel", String(50))
    time_period: Mapped[str | None] = mapped_column("timeperiod", String(50))
    update_frequency: Mapped[str | None] = mapped_column("updatefrequency", String(50))
    license_text: Mapped[str | None] = mapped_column("licensetext", String(200))
    storage_zone: Mapped[str | None] = mapped_column("storagezone", String(100))
    ingestion_date: Mapped[date | None] = mapped_column("ingestiondate", Date)
    status: Mapped[str | None] = mapped_column("status", String(20))

    assets: Mapped[list["DataAsset"]] = relationship(back_populates="dataset")


class DataAsset(Base):
    """One physical file in the data lake, with its recorded checksum.

    schema_version doubles as the raw-asset version label ('v1', 'v2', ...)
    for the unstructured source. status is 'Stored' for the current version
    and 'Superseded' for earlier ones; superseded files are kept on disk.
    """

    __tablename__ = "data_asset"

    asset_id: Mapped[int] = mapped_column(
        "assetid", Integer, Sequence("data_asset_assetid_seq"), primary_key=True)
    dataset_id: Mapped[str | None] = mapped_column(
        "datasetid", String(10), ForeignKey("dataset.datasetid"))
    file_name: Mapped[str] = mapped_column("filename", String(200))
    relative_path: Mapped[str | None] = mapped_column("relativepath", String(300))
    cloud_uri: Mapped[str | None] = mapped_column("clouduri", String(1000))
    file_format: Mapped[str | None] = mapped_column("fileformat", String(20))
    asset_type: Mapped[str | None] = mapped_column("assettype", String(30))
    file_size_bytes: Mapped[int | None] = mapped_column("filesizebytes", BigInteger)
    row_count: Mapped[int | None] = mapped_column("rowcount", Integer)
    column_count: Mapped[int | None] = mapped_column("columncount", Integer)
    sha256: Mapped[str | None] = mapped_column("sha256", CHAR(64))
    schema_version: Mapped[str | None] = mapped_column("schemaversion", String(20))
    ingestion_date: Mapped[date | None] = mapped_column("ingestiondate", Date)
    status: Mapped[str | None] = mapped_column("status", String(20))

    dataset: Mapped["Dataset | None"] = relationship(back_populates="assets")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="asset")


class MLRun(Base):
    """One training execution.

    The active model is the most recently completed run:
    Status = 'Completed' with the greatest CompletedAt. A failed run is
    recorded with Status = 'Failed' and therefore can never become active,
    which is how a broken retraining leaves the previous model in place.
    """

    __tablename__ = "ml_run"

    ml_run_id: Mapped[int] = mapped_column("mlrunid", BigInteger, primary_key=True)
    model_name: Mapped[str] = mapped_column("modelname", String(100))
    model_version: Mapped[str] = mapped_column("modelversion", String(20))
    algorithm: Mapped[str] = mapped_column("algorithm", String(50))
    configuration_json: Mapped[dict] = mapped_column("configurationjson", JSONB)
    random_seed: Mapped[int] = mapped_column("randomseed", Integer)
    training_dataset_id: Mapped[str | None] = mapped_column(
        "trainingdatasetid", String(10), ForeignKey("dataset.datasetid"))
    started_at: Mapped[datetime] = mapped_column("startedat", DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        "completedat", DateTime(timezone=True))
    status: Mapped[str] = mapped_column("status", String(20))
    metrics_json: Mapped[dict | None] = mapped_column("metricsjson", JSONB)

    cluster_summaries: Mapped[list["MLClusterSummary"]] = relationship(
        back_populates="run", cascade="all, delete-orphan",
        order_by="MLClusterSummary.cluster_id")
    cluster_results: Mapped[list["MLClusterResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan")

    @property
    def source_asset_id(self) -> int | None:
        """AssetID recorded in the run metrics, if the run stored one."""
        return (self.metrics_json or {}).get("source_asset_id")

    @property
    def source_checksum(self) -> str | None:
        metrics = self.metrics_json or {}
        return metrics.get("source_sha256") or metrics.get("expected_sha256")


class DocumentChunk(Base):
    __tablename__ = "document_chunk"

    document_chunk_id: Mapped[int] = mapped_column(
        "documentchunkid", BigInteger, primary_key=True)
    data_asset_id: Mapped[int] = mapped_column(
        "dataassetid", Integer, ForeignKey("data_asset.assetid"))
    page_number: Mapped[int] = mapped_column("pagenumber", Integer)
    section_name: Mapped[str | None] = mapped_column("sectionname", String(200))
    chunk_text: Mapped[str] = mapped_column("chunktext", Text)
    word_count: Mapped[int] = mapped_column("wordcount", Integer)
    chunk_checksum: Mapped[str] = mapped_column("chunkchecksum", CHAR(64))
    created_at: Mapped[datetime | None] = mapped_column("createdat", DateTime(timezone=True), server_default=FetchedValue())

    asset: Mapped["DataAsset"] = relationship(back_populates="chunks")


class MLClusterResult(Base):
    __tablename__ = "ml_cluster_result"

    ml_run_id: Mapped[int] = mapped_column(
        "mlrunid", BigInteger, ForeignKey("ml_run.mlrunid", ondelete="CASCADE"),
        primary_key=True)
    document_chunk_id: Mapped[int] = mapped_column(
        "documentchunkid", BigInteger, ForeignKey("document_chunk.documentchunkid"),
        primary_key=True)
    cluster_id: Mapped[int] = mapped_column("clusterid", Integer)
    distance_to_centroid: Mapped[Decimal | None] = mapped_column(
        "distancetocentroid", Numeric(12, 6))
    relative_score: Mapped[Decimal | None] = mapped_column("relativescore", Numeric(8, 6))
    created_at: Mapped[datetime | None] = mapped_column("createdat", DateTime(timezone=True), server_default=FetchedValue())

    run: Mapped["MLRun"] = relationship(back_populates="cluster_results")
    chunk: Mapped["DocumentChunk"] = relationship()


class MLClusterSummary(Base):
    """Interpreted cluster output and the governance gate.

    human_reviewed must be TRUE, with a reviewer and a timestamp, before
    the cluster may be treated as anything other than raw model output.
    The database check constraint ck_mlcs_review keeps the three fields
    consistent; the application enforces that a reviewer is named.
    """

    __tablename__ = "ml_cluster_summary"

    ml_run_id: Mapped[int] = mapped_column(
        "mlrunid", BigInteger, ForeignKey("ml_run.mlrunid", ondelete="CASCADE"),
        primary_key=True)
    cluster_id: Mapped[int] = mapped_column("clusterid", Integer, primary_key=True)
    cluster_label: Mapped[str | None] = mapped_column("clusterlabel", String(200))
    top_terms_json: Mapped[list | None] = mapped_column("toptermsjson", JSONB)
    representative_chunks_json: Mapped[list | None] = mapped_column(
        "representativechunksjson", JSONB)
    business_interpretation: Mapped[str | None] = mapped_column(
        "businessinterpretation", Text)
    human_reviewed: Mapped[bool] = mapped_column("humanreviewed", Boolean)
    reviewed_at: Mapped[datetime | None] = mapped_column("reviewedat", DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column("reviewedby", String(100))

    run: Mapped["MLRun"] = relationship(back_populates="cluster_summaries")
    indicator_maps: Mapped[list["MLClusterIndicatorMap"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan")

    @property
    def top_terms(self) -> list[str]:
        return list(self.top_terms_json or [])


class MLClusterIndicatorMap(Base):
    """Part IV addition: the governed cluster-to-indicator link.

    A row asserts that a reviewed document theme corresponds to a
    structured HEALTH_INDICATOR already in the ODS. The application treats
    the mapping as an approved insight only when is_active is TRUE and the
    parent summary has human_reviewed TRUE.
    """

    __tablename__ = "ml_cluster_indicator_map"
    __table_args__ = (
        ForeignKeyConstraint(
            ["mlrunid", "clusterid"],
            ["ml_cluster_summary.mlrunid", "ml_cluster_summary.clusterid"],
            ondelete="CASCADE",
        ),
    )

    ml_cluster_indicator_map_id: Mapped[int] = mapped_column(
        "mlclusterindicatormapid", BigInteger, primary_key=True)
    ml_run_id: Mapped[int] = mapped_column("mlrunid", BigInteger)
    cluster_id: Mapped[int] = mapped_column("clusterid", Integer)
    health_indicator_id: Mapped[int] = mapped_column(
        "healthindicatorid", Integer, ForeignKey("health_indicator.indicatorid"))
    approved_by: Mapped[str] = mapped_column("approvedby", String(100))
    approved_at: Mapped[datetime | None] = mapped_column(
        "approvedat", DateTime(timezone=True), server_default=FetchedValue())
    review_notes: Mapped[str | None] = mapped_column("reviewnotes", String(500))
    is_active: Mapped[bool] = mapped_column("isactive", Boolean)
    created_at: Mapped[datetime | None] = mapped_column("createdat", DateTime(timezone=True), server_default=FetchedValue())

    cluster: Mapped["MLClusterSummary"] = relationship(back_populates="indicator_maps")
    indicator: Mapped["HealthIndicator"] = relationship()  # noqa: F821
