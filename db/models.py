import datetime

from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Analysis(Base):
    """One run of the impact pipeline against a single Terraform plan change."""

    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))

    plan_source = Column(String(255))
    resource_address = Column(String(255), index=True)
    resource_type = Column(String(100), index=True)
    change_action = Column(String(50))
    changed_attributes = Column(Text)

    affected_count = Column(Integer, default=0)
    impact_level = Column(String(20))
    risk_level = Column(String(20))
    confidence_score = Column(Float)

    dependency_path = Column(Text)
    affected_resources = Column(Text)
    recommendations = Column(Text)

    outcomes = relationship("IncidentOutcome", back_populates="analysis")


class IncidentOutcome(Base):
    """
    Manually-recorded real-world outcome for a past analysis, e.g. "this
    caused an outage". Used to power the Similar Past Changes panel with
    real history instead of a hardcoded table.
    """

    __tablename__ = "incident_outcomes"

    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False)
    outcome_text = Column(String(255))
    was_incident = Column(Boolean, default=False)
    recorded_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))

    analysis = relationship("Analysis", back_populates="outcomes")
