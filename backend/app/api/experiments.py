"""Experimental features for the signed-in person: what's available, and opting in."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict

from app.api import deps
from app.api.deps import SessionDep
from app.services import experiments as service

router = APIRouter(prefix="/api/v1", tags=["experiments"])


class MyExperimentOut(BaseModel):
    name: str
    title: str
    description: str
    risks: str
    opted_in: bool


class MyExperimentsOut(BaseModel):
    enabled: bool
    features: list[MyExperimentOut]


class OptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opted_in: bool


@router.get("/experiments")
async def my_experiments(session: SessionDep, request: Request) -> MyExperimentsOut:
    enabled, features = await service.for_user(deps.database(request), session)
    return MyExperimentsOut(
        enabled=enabled,
        features=[
            MyExperimentOut(
                name=f.name,
                title=f.experiment.title,
                description=f.experiment.description,
                risks=f.experiment.risks,
                opted_in=f.opted_in,
            )
            for f in features
        ],
    )


@router.put("/experiments/{name}", status_code=204)
async def opt_in(
    name: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_.]{1,59}$")],
    body: OptIn,
    session: SessionDep,
    request: Request,
) -> None:
    try:
        await service.opt_in(deps.database(request), session, name, body.opted_in)
    except service.UnknownExperimentError as exc:
        raise HTTPException(404, str(exc)) from None
