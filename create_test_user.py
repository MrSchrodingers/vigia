import logging
from sqlalchemy.orm import Session
from db.session import SessionLocal
from db.models import User
from vigia.services.crud import get_user_by_email, get_password_hash

# Configuração básica de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- DEFINA AQUI AS CREDENCIAIS DO SEU USUÁRIO DE TESTE ---
TEST_USER_EMAIL = "advogado@exemplo.com"
TEST_USER_PASSWORD = "senha123"
# ---------------------------------------------------------

def create_user():
    """
    Cria um usuário de teste no banco de dados se ele ainda não existir.
    """
    logging.info("Iniciando o script para criar usuário de teste...")
    db: Session = SessionLocal()
    
    try:
        # Verifica se o usuário já existe
        user = get_user_by_email(db, email=TEST_USER_EMAIL)
        
        if user:
            logging.warning(f"O usuário '{TEST_USER_EMAIL}' já existe no banco de dados.")
            return

        # Se não existir, cria o novo usuário
        logging.info(f"Usuário '{TEST_USER_EMAIL}' não encontrado. Criando...")
        
        hashed_password = get_password_hash(TEST_USER_PASSWORD)
        new_user = User(email=TEST_USER_EMAIL, hashed_password=hashed_password)
        
        db.add(new_user)
        db.commit()
        
        logging.info("=" * 40)
        logging.info("✅ Usuário de teste criado com sucesso!")
        logging.info(f"   Email: {TEST_USER_EMAIL}")
        logging.info(f"   Senha: {TEST_USER_PASSWORD}")
        logging.info("=" * 40)

    except Exception as e:
        logging.error(f"Ocorreu um erro ao tentar criar o usuário: {e}")
        db.rollback()
    finally:
        db.close()
        logging.info("Script finalizado.")

if __name__ == "__main__":
    create_user()