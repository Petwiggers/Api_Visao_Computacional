from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
import psutil
from infra.database import get_async_db
from infra.orm.UsuarioModel import UsuarioDB

router = APIRouter()

# Health check básico - Verificação básica de saúde da API - Usado por load balancers e orquestradores
@router.get(
    "/health",
    tags=["Health"],
    summary="Health check básico - Verificação básica de saúde da API - Usado por load balancers e orquestradores"
)
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "comandas-api",
        "version": "1.0.0"
    }

# Health check do banco de dados - Verifica conexão com banco de dados - Testa se consegue executar query simples
@router.get(
    "/health/database",
    tags=["Health"],
    summary="Health check do banco de dados - Verifica conexão com banco de dados - Testa se consegue executar query simples"
)
async def database_health(db: AsyncSession = Depends(get_async_db)):
    try:
        # Query simples para testar conexão
        result = await db.execute(text("SELECT 1 as test"))
        row = result.fetchone()
        if row and row[0] == 1:
            return {
                "status": "healthy",
                "database": "connected",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database query failed"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unavailable: {str(e)}"
        )

# Health check das tabelas - Verifica se tabelas críticas existem e têm dados
@router.get(
    "/health/database/tables",
    tags=["Health"],
    summary="Health check das tabelas - Verifica se tabelas críticas existem e têm dados"
)
async def database_tables_health(db: AsyncSession = Depends(get_async_db)):
    try:
        # Verifica tabelas críticas
        checks = {}
        # Verifica tabela funcionário
        try:
            from sqlalchemy import select, func
            result = await db.execute(select(func.count()).select_from(UsuarioDB))
            count = result.scalar()
            checks["usuarios"] = {
                "status": "healthy",
                "count": count
            }
        except Exception as e:
            checks["usuarios"] = {
                "status": "error",
                "error": str(e)
            }
        # Verifica se todas estão healthy
        all_healthy = all(
            check["status"] == "healthy"
            for check in checks.values()
        )
        return {
            "status": "healthy" if all_healthy else "unhealthy",
            "tables": checks,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database tables check failed: {str(e)}"
        )

# Health check do sistema - Verifica recursos do sistema (memória, disco, CPU)
@router.get(
    "/health/system",
    tags=["Health"],
    summary="Health check do sistema - Verifica recursos do sistema (memória, disco, CPU)"
)
async def system_health():
    try:
        # Informações de memória
        memory = psutil.virtual_memory()
        memory_info = {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent,
            "used": memory.used,
            "status": "healthy" if memory.percent < 90 else "warning"
        }
        # Informações de disco
        disk = psutil.disk_usage('.')  # Diretório atual em vez de raiz
        disk_info = {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": (disk.used / disk.total) * 100,
            "status": "healthy" if (disk.used / disk.total) * 100 < 90 else "warning"
        }
        # Informações de CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_info = {
            "percent": cpu_percent,
            "count": psutil.cpu_count(),
            "status": "healthy" if cpu_percent < 80 else "warning"
        }
        # Status geral
        all_healthy = all([
            memory_info["status"] == "healthy",
            disk_info["status"] == "healthy",
            cpu_info["status"] == "healthy"
        ])
        return {
            "status": "healthy" if all_healthy else "warning",
            "memory": memory_info,
            "disk": disk_info,
            "cpu": cpu_info,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"System health check failed: {str(e)}"
        )

# Health check completo - Verificação completa de todos os componentes
@router.get(
    "/health/full",
    tags=["Health"],
    summary="Health check completo - Verificação completa de todos os componentes"
)
async def full_health_check(db: AsyncSession = Depends(get_async_db)):
    try:
        # Coleta todos os health checks
        checks = {}
        # API Status
        checks["api"] = {"status": "healthy", "message": "API responding"}
        # Database Status
        try:
            await db.execute(text("SELECT 1"))
            checks["database"] = {"status": "healthy", "message": "Database connected"}
        except Exception as e:
            checks["database"] = {"status": "unhealthy", "message": str(e)}
        # System Status
        try:
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('.')  # Diretório atual
            cpu = psutil.cpu_percent(interval=1)
            system_healthy = (
                memory.percent < 90 and
                (disk.used / disk.total) * 100 < 90 and
                cpu < 80
            )
            checks["system"] = {
                "status": "healthy" if system_healthy else "warning",
                "memory_percent": memory.percent,
                "disk_percent": (disk.used / disk.total) * 100,
                "cpu_percent": cpu
            }
        except Exception as e:
            checks["system"] = {"status": "error", "message": str(e)}
        # Status geral
        overall_status = "healthy"
        for check in checks.values():
            if check["status"] == "unhealthy":
                overall_status = "unhealthy"
                break
            elif check["status"] == "warning" and overall_status == "healthy":
                overall_status = "warning"
            elif check["status"] == "error":
                overall_status = "unhealthy"
                break
        return {
            "status": overall_status,
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "comandas-api",
            "version": "1.0.0"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Full health check failed: {str(e)}"
        )

# Readiness probe - Verifica se API está pronta para receber tráfego - Similar ao health mas pode incluir verificações adicionais
@router.get(
    "/ready",
    tags=["Health"],
    summary="Readiness probe - Verifica se API está pronta para receber tráfego - Similar ao health mas pode incluir verificações adicionais"
)
async def readiness_check(db: AsyncSession = Depends(get_async_db)):
    # Verifica se banco está acessível
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service not ready - database unavailable: {str(e)}"
        )
    return {
        "status": "ready",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# Liveness probe - Verifica se API está viva (não travada) - Usado por Kubernetes para reiniciar containers travados
@router.get(
    "/live",
    tags=["Health"],
    summary="Liveness probe - Verifica se API está viva (não travada) - Usado por Kubernetes para reiniciar containers travados"
)
async def liveness_check():
    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime": "running"
    } 