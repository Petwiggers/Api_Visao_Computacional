#Peterson Wiggers
from infra import database
from sqlalchemy import Column, VARCHAR, CHAR, Integer
from fastapi import HTTPException, status

# ORM
class UsuarioDB(database.Base):
    __tablename__ = 'tb_usuario'
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    nome = Column(VARCHAR(100), nullable=False)
    email = Column(CHAR(10), nullable=False)
    cpf = Column(CHAR(11), unique=True, nullable=False, index=True)
    telefone = Column(CHAR(11), nullable=False)
    grupo = Column(Integer, nullable=False)
    senha = Column(VARCHAR(200), nullable=False)
    def __init__(self, id, nome, email, cpf, telefone, grupo, senha):
        self.id = id
        if(nome == None or nome.strip() == ""):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O nome do usuário é obrigatório.");
        if(email == None or email.strip() == ""):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O email do usuário é obrigatório.");
        if(cpf == None or cpf.strip() == ""):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O CPF do usuário é obrigatório.");
        if(telefone == None or telefone.strip() == ""):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O telefone do usuário é obrigatório.");
        if(grupo == None):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O grupo do usuário é obrigatório.");
        if(grupo != 1 and grupo != 2 and grupo != 3):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O grupo do usuário deve ser 1, 2 ou 3.");
        self.nome = nome
        self.email = email
        self.cpf = cpf
        self.telefone = telefone
        self.grupo = grupo
        self.senha = senha