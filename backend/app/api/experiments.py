from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.experiments import (ApproveIn, ExperimentCreate, ExperimentOut, ExperimentUpdate,
                                     OutcomeIn, OutcomeOut, StartIn)
from app.services import experiment_service as svc

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    return svc.impact_summary(db)


@router.get("", response_model=list[ExperimentOut])
def list_all(status: str | None = None, db: Session = Depends(get_db)):
    return svc.list_experiments(db, status)


@router.post("", response_model=ExperimentOut, status_code=201)
def create(body: ExperimentCreate, db: Session = Depends(get_db)):
    return svc.create_experiment(db, body)


@router.get("/{exp_id}", response_model=ExperimentOut)
def get_one(exp_id: int, db: Session = Depends(get_db)):
    return svc.get_experiment(db, exp_id)


@router.patch("/{exp_id}", response_model=ExperimentOut)
def edit(exp_id: int, body: ExperimentUpdate, db: Session = Depends(get_db)):
    return svc.update_proposal(db, exp_id, body)


@router.post("/{exp_id}/approve", response_model=ExperimentOut)
def approve(exp_id: int, body: ApproveIn | None = None, db: Session = Depends(get_db)):
    return svc.approve(db, exp_id, (body.approved_by if body else "retailer"))


@router.post("/{exp_id}/reject", response_model=ExperimentOut)
def reject(exp_id: int, db: Session = Depends(get_db)):
    return svc.reject(db, exp_id)


@router.post("/{exp_id}/cancel", response_model=ExperimentOut)
def cancel(exp_id: int, db: Session = Depends(get_db)):
    return svc.cancel(db, exp_id)


@router.post("/{exp_id}/start", response_model=ExperimentOut)
def start(exp_id: int, body: StartIn, db: Session = Depends(get_db)):
    return svc.start(db, exp_id, body.start_date, body.end_date)


@router.post("/{exp_id}/outcome", response_model=OutcomeOut, status_code=201)
def record_outcome(exp_id: int, body: OutcomeIn, db: Session = Depends(get_db)):
    return svc.record_outcome(db, exp_id, body)


@router.get("/{exp_id}/outcome", response_model=OutcomeOut)
def get_outcome(exp_id: int, db: Session = Depends(get_db)):
    return svc.get_outcome(db, exp_id)
