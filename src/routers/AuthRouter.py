from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta

from domain.schemas.AuthSchema import (
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    UsuarioAuth,
)
from infra.orm.UsuarioModel import UsuarioDB
from infra.database import get_async_db
from infra.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
)
from infra.dependencies import get_current_active_user
from infra.rate_limit import get_rate_limit, limiter 
from services.AuditoriaService import AuditoriaService
from settings import ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS

router = APIRouter()


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    tags=["Autenticação"],
    summary="Login de funcionário - pública - retorna access e refresh token",
)
@limiter.limit(get_rate_limit("critical"))
async def login(request: Request, login_data: LoginRequest, db: AsyncSession = Depends(get_async_db)):
    """Realiza login do usuário e retorna access token e refresh token."""
    try:
        result = await db.execute(select(UsuarioDB).where(UsuarioDB.email == login_data.email))
        usuario = result.scalar_one_or_none()

        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou senha inválidos",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not verify_password(login_data.senha, usuario.senha):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou senha inválidos",
                headers={"WWW-Authenticate": "Bearer"},
            )

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={
                "sub": usuario.cpf,
                "id": usuario.id,
                "grupo": usuario.grupo
            },
            expires_delta=access_token_expires
        )

        refresh_token = create_refresh_token(
            data={
                "sub": usuario.cpf,
                "id": usuario.id,
                "grupo": usuario.grupo
            }
        )
        
        # Registrar auditoria de login
        AuditoriaService.registrar_acao(
            db=db,
            funcionario_id=usuario.id,
            acao="LOGIN",
            recurso="AUTH",
            request=request
            )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            refresh_expires_in=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao realizar login: {e}",
        )
        
@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    tags=["Autenticação"],
    summary="Refresh token - pública - renova access token",
)
@limiter.limit(get_rate_limit("critical"))
async def refresh_token(request: Request, refresh_data: RefreshTokenRequest, db: AsyncSession = Depends(get_async_db)):
    """Renova o access token usando um refresh token válido."""
    try:
        payload = verify_refresh_token(refresh_data.refresh_token)
        email = payload.get("sub")
        result = await db.execute(select(UsuarioDB).where(UsuarioDB.email == email))
        usuario = result.scalar_one_or_none()

        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuário não encontrado",
                headers={"WWW-Authenticate": "Bearer"},
            )

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={
                "sub": usuario.cpf,
                "id": usuario.id,
                "grupo": usuario.grupo,
            },
            expires_delta=access_token_expires,
        )

        new_refresh_token = create_refresh_token(
            data={
                "sub": usuario.cpf,
                "id": usuario.id,
                "grupo": usuario.grupo,
            }
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            refresh_expires_in=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Erro ao renovar token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
@router.get("/auth/me", response_model=UsuarioAuth, tags=["Autenticação"], summary="Dados do usuário atual - protegida por autenticação")
@limiter.limit(get_rate_limit("moderate"))
async def get_current_user_info(request: Request,current_user: UsuarioAuth = Depends(get_current_active_user)):
    """
    Retorna informações do usuário autenticado atual
    Requer header: Authorization: Bearer <access_token>
    """
    return current_user

@router.post("/auth/logout", tags=["Autenticação"], summary="Logout - pública")
@limiter.limit(get_rate_limit("moderate"))
async def logout(request: Request):
    """
    Endpoint para logout (client-side)
    Na prática, o logout é implementado no cliente removendo os tokens
    Este endpoint existe apenas para completude da API
    """
    return {"message": "Logout realizado com sucesso"}
