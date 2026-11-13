"""Modelo relacional do Atlas.

Centrado em: catálogo de fontes/bases, catálogo de indicadores, metodologias,
dimensão territorial (códigos IBGE), observações versionadas e execuções de carga.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    """Instituição produtora dos dados."""

    __tablename__ = "source"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(500))
    license: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    datasets: Mapped[list["Dataset"]] = relationship(back_populates="source")


class Dataset(Base):
    """Base/tabela/arquivo específico de uma fonte (ex.: SIDRA 5938, ESTBAN)."""

    __tablename__ = "dataset"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source.id"))
    name: Mapped[str] = mapped_column(String(300))
    endpoint: Mapped[str | None] = mapped_column(String(600))
    format: Mapped[str | None] = mapped_column(String(60))
    access: Mapped[str | None] = mapped_column(String(60))  # api | arquivo
    periodicity: Mapped[str | None] = mapped_column(String(40))
    coverage: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="integrado")  # integrado | planejado
    source: Mapped[Source] = relationship(back_populates="datasets")


class Methodology(Base):
    __tablename__ = "methodology"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(20), default="1")


class Unit(Base):
    __tablename__ = "unit"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(80))
    # Dimensões físicas para validação de fórmulas, ex.: {"BRL": 1, "pessoa": -1}
    dims: Mapped[dict] = mapped_column(JSON, default=dict)
    percent: Mapped[bool] = mapped_column(Boolean, default=False)


class Indicator(Base):
    __tablename__ = "indicator"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    dimension: Mapped[str] = mapped_column(String(40), index=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("unit.id"))
    nature: Mapped[str] = mapped_column(String(20))  # observado | derivado | estimado
    value_kind: Mapped[str] = mapped_column(String(20))  # nominal | quantidade | razao | taxa | indice
    stock_flow: Mapped[str] = mapped_column(String(10), default="na")  # estoque | fluxo | na
    frequency: Mapped[str] = mapped_column(String(2), default="A")  # A | M
    additive: Mapped[bool] = mapped_column(Boolean, default=False)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("dataset.id"))
    methodology_id: Mapped[str | None] = mapped_column(ForeignKey("methodology.id"))
    formula: Mapped[str | None] = mapped_column(Text)  # indicadores derivados
    levels: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="disponivel")  # disponivel | planejado
    limitations: Mapped[str | None] = mapped_column(Text)
    breaks: Mapped[list] = mapped_column(JSON, default=list)  # quebras metodológicas
    decimals: Mapped[int] = mapped_column(Integer, default=2)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[Unit] = relationship()
    dataset: Mapped[Dataset | None] = relationship()
    methodology: Mapped[Methodology | None] = relationship()


class Territory(Base):
    """Unidades territoriais com códigos oficiais do IBGE.

    Níveis: BR, REGIAO (1 díg.), UF (2), RGINT (4), RGI (6), MUN (7).
    """

    __tablename__ = "territory"
    code: Mapped[str] = mapped_column(String(7), primary_key=True)
    level: Mapped[str] = mapped_column(String(8), index=True)
    name: Mapped[str] = mapped_column(String(120))
    name_norm: Mapped[str] = mapped_column(String(120), index=True)
    sigla: Mapped[str | None] = mapped_column(String(4))
    regiao_code: Mapped[str | None] = mapped_column(String(1), index=True)
    uf_code: Mapped[str | None] = mapped_column(String(2), index=True)
    rgint_code: Mapped[str | None] = mapped_column(String(4))
    rgi_code: Mapped[str | None] = mapped_column(String(6))


class TerritoryChange(Base):
    """Alterações da malha municipal (criação, desmembramento, fusão)."""

    __tablename__ = "territory_change"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(ForeignKey("territory.code"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # instalacao | cessao_de_area
    year: Mapped[int] = mapped_column(Integer)
    related_codes: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("code", "kind", "year"),)


class IngestionRun(Base):
    """Histórico de cargas: base, parâmetros, publicação e resultado."""

    __tablename__ = "ingestion_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline: Mapped[str] = mapped_column(String(60), index=True)
    dataset_id: Mapped[str | None] = mapped_column(String(60))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | ok | erro
    publication: Mapped[str | None] = mapped_column(String(200))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    rows_new: Mapped[int] = mapped_column(Integer, default=0)
    rows_revised: Mapped[int] = mapped_column(Integer, default=0)
    rows_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Observation(Base):
    """Observação estatística versionada.

    `value` nulo nunca é convertido em zero; `flag` explica a ausência
    (nd = não disponível, sigilo = suprimido, na = não se aplica) ou anota o
    valor (agg = agregado pelo Atlas a partir dos municípios).
    Revisões: uma nova publicação com valor diferente gera nova linha
    (revision+1) e a anterior permanece com is_current = False.
    """

    __tablename__ = "observation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    indicator_id: Mapped[str] = mapped_column(ForeignKey("indicator.id"))
    territory_code: Mapped[str] = mapped_column(ForeignKey("territory.code"))
    level: Mapped[str] = mapped_column(String(8))
    period: Mapped[str] = mapped_column(String(7))  # 'AAAA' ou 'AAAA-MM'
    value: Mapped[float | None] = mapped_column(Float)
    flag: Mapped[str | None] = mapped_column(String(10))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_run.id"))
    __table_args__ = (
        UniqueConstraint("indicator_id", "territory_code", "period", "revision"),
        Index("ix_obs_lookup", "indicator_id", "level", "period", "is_current"),
        Index("ix_obs_terr", "territory_code", "indicator_id", "is_current"),
    )


class SavedView(Base):
    """Configurações de visualizações e indicadores personalizados salvos."""

    __tablename__ = "saved_view"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(30))  # mapa | dispersao | indicador
    name: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
