import bcrypt
senha = "123456"
salt = bcrypt.gensalt()
hashed = bcrypt.hashpw(senha.encode('utf-8'), salt)
print(hashed.decode('utf-8'))