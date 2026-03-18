import os

def reset_total():
    arquivo_db = "finance.db"
    if os.path.exists(arquivo_db):
        os.remove(arquivo_db)
        print(f"✅ O ficheiro {arquivo_db} foi removido. O sistema será recriado no próximo login.")
    else:
        print("⚠️ O ficheiro de base de dados não foi encontrado.")

if __name__ == "__main__":
    reset_total()
