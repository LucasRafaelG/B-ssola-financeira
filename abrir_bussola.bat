@echo off
rem Abre o aplicativo da Bussola no navegador. Para fechar, feche esta janela.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo O ambiente virtual .venv nao foi encontrado nesta pasta.
    echo Veja a secao "Como rodar" do README.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run "app\Bussola.py"
if errorlevel 1 pause
