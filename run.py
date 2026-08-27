import uvicorn

if __name__ == "__main__":
    print("--------------------------------------------------")
    print("   INICIANDO SERVIDOR DEL TRACKER DE ACCIONES     ")
    print("   Consola disponible en: http://127.0.0.1:8000   ")
    print("--------------------------------------------------")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
