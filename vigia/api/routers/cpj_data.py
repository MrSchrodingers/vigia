from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from db.models import CPJProcess
from vigia.api import dependencies, schemas

router = APIRouter(
    prefix="/api/cpj-data",
    tags=["CPJ Data"],
    dependencies=[Depends(dependencies.get_current_user)],
)


@router.get("/{legal_process_id}", response_model=schemas.CPJProcessDetails)
def read_cpj_process_details(
    legal_process_id: str,
    db: Session = Depends(dependencies.get_db),
):
    """
    Retorna os dados detalhados de um processo que foram importados do CPJ.
    """
    cpj_data = (
        db.query(CPJProcess)
        .options(
            selectinload(CPJProcess.parties),
            selectinload(CPJProcess.movements),
        )
        .filter(CPJProcess.legal_process_id == legal_process_id)
        .first()
    )

    if not cpj_data:
        raise HTTPException(
            status_code=404, detail="Dados do CPJ não encontrados para este processo."
        )

    return cpj_data
