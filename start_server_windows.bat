@echo off
echo 🚀 Запуск проекта FaceSort на Windows...
echo 📁 Рабочая директория: %cd%
python --version
echo.
echo 📋 FaceSort установит следующие зависимости:
echo    ✅ FastAPI, Uvicorn, Pillow, OpenCV, NumPy, Scikit-learn
echo    ✅ InsightFace (обязательно), dlib, face-recognition
echo    🔄 RetinaFace, FaceNet-PyTorch (опционально, улучшают распознавание)
echo.

echo 📦 Проверяем виртуальное окружение...
if not exist venv (
    echo 🔧 Создаем виртуальное окружение...
    python -m venv venv
    if errorlevel 1 (
        echo ❌ Ошибка создания виртуального окружения
        echo 📋 Возможные причины:
        echo    • Python не установлен или не в PATH
        echo    • Нет прав на создание папок
        echo    • Недостаточно места на диске
        pause
        exit /b 1
    )
    echo ✅ Виртуальное окружение создано
) else (
    echo ✅ Виртуальное окружение найдено
)

timeout /t 1 >nul

echo 🔄 Активируем виртуальное окружение...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ❌ Ошибка активации виртуального окружения
    echo 📋 Возможные причины:
    echo    • Повреждено виртуальное окружение
    echo    • Неправильный путь к activate.bat
    echo    • Отсутствуют права на выполнение
    echo 🔧 Попробуйте удалить папку venv и запустить заново
    pause
    exit /b 1
)
echo ✅ Виртуальное окружение активировано

REM Проверяем, что Python доступен в виртуальном окружении
python --version
if errorlevel 1 (
    echo ❌ Python недоступен в виртуальном окружении
    pause
    exit /b 1
)
echo.

echo 📦 Проверяем зависимости...
python -c "import fastapi, uvicorn, PIL, cv2, numpy, sklearn, packaging" 2>nul
if errorlevel 1 (
    echo ❌ Некоторые базовые зависимости не установлены.
    echo 🔧 Начинаем установку зависимостей...
    echo 📋 Это может занять 10-30 минут в зависимости от скорости интернета
    timeout /t 3 >nul

    echo 📥 Шаг 1: Обновляем pip...
    python -m pip install --upgrade pip
    if errorlevel 1 (
        echo ⚠️ Не удалось обновить pip системно, пробуем для пользователя...
        pip install --user --upgrade pip
    )

    echo 📥 Шаг 2: Устанавливаем основные пакеты...
    pip install fastapi==0.104.1 uvicorn[standard]==0.24.0 python-multipart==0.0.6 pydantic==2.5.0 pillow==10.1.0 psutil==5.9.6 numpy==1.24.3 opencv-python==4.8.1.78 scikit-learn==1.3.2 hdbscan==0.8.33 httpx==0.25.0 packaging>=21.0
    if errorlevel 1 (
        echo ⚠️ Ошибка установки основных пакетов, пробуем по одному...
        echo 📦 Устанавливаем FastAPI и веб-фреймворки...
        pip install --user fastapi==0.104.1 uvicorn[standard]==0.24.0 python-multipart==0.0.6 pydantic==2.5.0
        if errorlevel 1 (
            echo ❌ Не удалось установить веб-фреймворки
            pause
            exit /b 1
        )
        echo 📦 Устанавливаем библиотеки изображений...
        pip install --user pillow==10.1.0 psutil==5.9.6 opencv-python==4.8.1.78
        if errorlevel 1 (
            echo ❌ Не удалось установить библиотеки изображений
            pause
            exit /b 1
        )
        echo 📦 Устанавливаем ML библиотеки...
        pip install --user numpy==1.24.3 scikit-learn==1.3.2 hdbscan==0.8.33 httpx==0.25.0 packaging>=21.0
        if errorlevel 1 (
            echo ❌ Не удалось установить ML библиотеки
            pause
            exit /b 1
        )
    )
    echo ✅ Основные пакеты установлены
    timeout /t 2 >nul

    echo 📥 Шаг 3: Устанавливаем ML пакеты...
    echo 🔧 Устанавливаем InsightFace (это займет несколько минут)...
    call install_insightface_windows.bat
    if errorlevel 1 (
        echo ❌ InsightFace не удалось установить
        echo 🔧 FaceSort не сможет работать без InsightFace
        echo 📋 Возможные решения:
        echo    • Проверьте подключение к интернету
        echo    • Попробуйте запустить install_insightface_windows.bat отдельно
        echo    • Скачайте модели InsightFace вручную
        pause
        exit /b 1
    )
    echo ✅ InsightFace установлен
    timeout /t 2 >nul

    echo 📥 Шаг 4: Устанавливаем dlib и face-recognition...
    echo 🔧 dlib может требовать Visual Studio Build Tools...
    echo 📋 Если установка dlib не удастся, установите вручную:
    echo    pip install dlib==19.24.6
    echo    или скачайте wheel с https://pypi.org/project/dlib/#files
    pip install dlib==19.24.6
    if errorlevel 1 (
        echo ❌ dlib не установился автоматически
        echo 🔧 Попробуйте один из вариантов:
        echo    1. Скачайте wheel файл для вашей версии Python с https://pypi.org/project/dlib/#files
        echo    2. pip install cmake
        echo       pip install dlib==19.24.6
        echo    3. conda install -c conda-forge dlib
        echo.
        echo ⏳ Продолжаем без dlib...
    )

    pip install face-recognition==1.3.0 face-recognition-models==0.3.0
    if errorlevel 1 (
        echo ⚠️ face-recognition не установился
        echo 🔧 FaceSort будет работать без него
    ) else (
        echo ✅ face-recognition установлен
    )
    timeout /t 1 >nul

    echo 📥 Шаг 5: Устанавливаем опциональные улучшения распознавания...
    echo 🔧 RetinaFace (улучшенная детекция лиц)...
    pip install retinaface --no-deps
    if errorlevel 1 (
        echo ⚠️ RetinaFace не установился, продолжаем без него
    ) else (
        echo ✅ RetinaFace установлен
    )

    echo 🔧 FaceNet-PyTorch (улучшенные эмбеддинги)...
    pip install facenet-pytorch
    if errorlevel 1 (
        echo ⚠️ FaceNet-PyTorch не установился, продолжаем без него
    ) else (
        echo ✅ FaceNet-PyTorch установлен
    )

    echo 🔧 PyTorch (для FaceNet, если не установлен)...
    pip install torch>=1.7.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
    if errorlevel 1 (
        echo ⚠️ PyTorch не установился, FaceNet может работать медленнее
    ) else (
        echo ✅ PyTorch установлен
    )
    timeout /t 2 >nul

    echo 📥 Шаг 6: Проверяем установку...
    python -c "import fastapi, uvicorn, PIL, cv2, numpy, sklearn, packaging" 2>nul
    if errorlevel 1 (
        echo ❌ Основные пакеты не установлены
        echo 🔧 Проверьте логи выше и установите пакеты вручную
        pause
        exit /b 1
    ) else (
        echo ✅ Основные зависимости установлены
    )

    python -c "import insightface; fa = insightface.app.FaceAnalysis(); fa.prepare(ctx_id=-1)" 2>nul
    if errorlevel 1 (
        echo ❌ InsightFace не работает корректно
        echo 🔧 Запустите install_insightface_windows.bat отдельно
    ) else (
        echo ✅ InsightFace полностью работает
    )

    echo 📋 Проверяем опциональные пакеты...
    python -c "import retinaface" 2>nul
    if errorlevel 1 (
        echo ⚠️ RetinaFace не установлен (опционально)
    ) else (
        echo ✅ RetinaFace установлен
    )

    python -c "import facenet_pytorch" 2>nul
    if errorlevel 1 (
        echo ⚠️ FaceNet-PyTorch не установлен (опционально)
    ) else (
        echo ✅ FaceNet-PyTorch установлен
    )

) else (
    echo ✅ Основные зависимости установлены
)
echo.

echo 🛑 Останавливаем предыдущие процессы...
taskkill /f /im python.exe /fi "WINDOWTITLE eq main.py*" >nul 2>&1
taskkill /f /im python.exe /fi "IMAGENAME eq python.exe" /fi "MEMUSAGE gt 100000" >nul 2>&1
timeout /t 2 >nul

echo 🚀 Запускаем сервер FaceSort...
echo 📋 Если сервер не запустится, проверьте логи выше на ошибки
start "FaceSort Server" python main.py

echo ✅ Сервер запущен!
echo 🌐 URL: http://localhost:8000
echo 📊 Проверка через 5 секунд...
timeout /t 5 >nul

REM Проверяем, что сервер действительно работает
powershell -Command "try { $response = Invoke-WebRequest -Uri 'http://localhost:8000' -TimeoutSec 10; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo ⚠️ Сервер может не работать корректно
    echo 📋 Проверьте логи сервера в другом окне
    echo 🔧 Попробуйте запустить python main.py вручную
) else (
    echo ✅ Сервер отвечает на запросы
)

echo.
echo 🎉 Установка завершена! FaceSort готов к работе.
echo 📋 Для остановки сервера закройте окно командной строки или нажмите Ctrl+C
echo 🎯 Откройте http://localhost:8000 в браузере
echo.
echo 💡 Советы:
echo    • RetinaFace улучшает детекцию лиц (особенно маленьких)
echo    • FaceNet-PyTorch дает более точные эмбеддинги
echo    • Без них FaceSort работает на базе InsightFace
echo.
pause
