@echo off
cd /d "%~dp0"
git remote set-url origin https://github.com/dreamerzlcoud/inklab.git 2>nul || git remote add origin https://github.com/dreamerzlcoud/inklab.git
git push -u origin HEAD:main --force
git push -u origin HEAD:master --force
git push origin --tags -f
pause
