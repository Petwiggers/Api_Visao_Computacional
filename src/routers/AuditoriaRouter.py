from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from domain.schemas.AuditoriaSchema import AuditoriaResponse
from domain.schemas.AuthSchema import UsuarioAuth
from infra.database import get_async_db
from infra.dependencies import require_group
from infra.orm.AuditoriaModel import AuditoriaDB
from infra.orm.UsuarioModel import UsuarioDB
from infra.rate_limit import get_rate_limit, limiter

router = APIRouter()


@router.get(
    "/auditoria",
    response_model=List[AuditoriaResponse],
    tags=["Auditoria"],
    summary="Listar registros de auditoria - protegida por JWT e grupo 1",
)
@limiter.limit(get_rate_limit("moderate"))
async def listar_auditoria(
    request: Request,
    skip: int = Query(0, ge=0, description="Número de registros para pular"),
    limite: int = Query(100, ge=1, le=1000, description="Limite de registros"),
    id: Optional[int] = Query(None, description="Filtrar por ID da auditoria"),
    funcionario_id: Optional[int] = Query(None, description="Filtrar por funcionário"),
    acao: Optional[str] = Query(None, description="Filtrar por ação (separar múltiplas com vírgula)"),
    recurso: Optional[str] = Query(None, description="Filtrar por recurso (separar múltiplos com vírgula)"),
    recurso_id: Optional[int] = Query(None, description="Filtrar por ID do recurso"),
    ip_address: Optional[str] = Query(None, description="Filtrar por endereço IP"),
    user_agent: Optional[str] = Query(None, description="Filtrar por User Agent"),
    data_inicio: Optional[str] = Query(None, description="Data início (YYYY-MM-DD)"),
    data_fim: Optional[str] = Query(None, description="Data fim (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_async_db),
    current_user: UsuarioAuth = Depends(require_group([1])),
):
    """
    Lista registros de auditoria com filtros opcionais.
    
    Apenas administradores podem acessar.
    """
    try:
        # Construir query base com joins
        query = select(AuditoriaDB, UsuarioDB).outerjoin(
            UsuarioDB, UsuarioDB.id == AuditoriaDB.funcionario_id
        )
        
        # Aplicar filtros
        if id is not None:
            query = query.where(AuditoriaDB.id == id)
        if funcionario_id:
            query = query.where(AuditoriaDB.funcionario_id == funcionario_id)
        if acao:
            acoes_list = [a.strip().upper() for a in acao.split(",")]
            query = query.where(AuditoriaDB.acao.in_(acoes_list))
        if recurso:
            recursos_list = [r.strip().upper() for r in recurso.split(",")]
            query = query.where(AuditoriaDB.recurso.in_(recursos_list))
        if recurso_id is not None:
            query = query.where(AuditoriaDB.recurso_id == recurso_id)
        if ip_address is not None:
            query = query.where(AuditoriaDB.ip_address == ip_address)
        if user_agent is not None:
            query = query.where(AuditoriaDB.user_agent.ilike(f"%{user_agent}%"))
        if data_inicio:
            try:
                data_inicio_dt = datetime.strptime(data_inicio, "%Y-%m-%d")
                query = query.where(AuditoriaDB.data_hora >= data_inicio_dt)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Data início inválida. Use formato YYYY-MM-DD",
                )
        if data_fim:
            try:
                data_fim_dt = datetime.strptime(data_fim, "%Y-%m-%d")
                query = query.where(AuditoriaDB.data_hora <= data_fim_dt)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Data fim inválida. Use formato YYYY-MM-DD",
                )
        
        # Ordenar por data descendente, aplicar paginação
        result = await db.execute(
            query.order_by(desc(AuditoriaDB.data_hora))
            .offset(skip)
            .limit(limite)
        )
        auditorias = result.all()
        
        # Montar response
        result_list = []
        for auditoria, funcionario in auditorias:
            result_list.append(
                AuditoriaResponse(
                    id=auditoria.id,
                    funcionario_id=auditoria.funcionario_id,
                    funcionario={
                        "id": funcionario.id,
                        "nome": funcionario.nome,
                        "matricula": funcionario.matricula,
                        "grupo": funcionario.grupo,
                    } if funcionario else None,
                    acao=auditoria.acao,
                    recurso=auditoria.recurso,
                    recurso_id=auditoria.recurso_id,
                    dados_antigos=auditoria.dados_antigos,
                    dados_novos=auditoria.dados_novos,
                    ip_address=auditoria.ip_address,
                    user_agent=auditoria.user_agent,
                    data_hora=auditoria.data_hora,
                )
            )
        return result_list
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao listar auditoria: {str(e)}",
        )


@router.get(
    "/auditoria/acoes",
    tags=["Auditoria"],
    summary="Listar tipos de ações disponíveis para filtro - protegida por JWT e grupo 1",
)
@limiter.limit(get_rate_limit("light"))
async def listar_acoes_disponiveis(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: UsuarioAuth = Depends(require_group([1])),
):
    """
    Lista os tipos de ações e recursos disponíveis para filtro.
    Retorna apenas ações e recursos que possuem registros de auditoria.
    """
    try:
        # Buscar ações distintas
        acoes_result = await db.execute(select(AuditoriaDB.acao).distinct())
        acoes_db = acoes_result.all()
        
        # Buscar recursos distintas
        recursos_result = await db.execute(select(AuditoriaDB.recurso).distinct())
        recursos_db = recursos_result.all()

        # Montar response com dados reais do banco
        return {
            "acoes": [{"codigo": acao[0]} for acao in acoes_db],
            "recursos": [{"codigo": recurso[0]} for recurso in recursos_db],
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao listar ações e recursos: {str(e)}",
        )