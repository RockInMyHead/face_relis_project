from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import json
import functools
import concurrent.futures
import zipfile
import shutil
import asyncio
from pathlib import Path
import psutil
from PIL import Image, ImageOps
import uuid
import time
import tempfile
import re
from io import BytesIO

# Используем продвинутую кластеризацию с ArcFace
from cluster_advanced import build_plan_advanced, distribute_to_folders, process_group_folder, IMG_EXTS
print("✅ Используется PRODUCTION кластеризация (ArcFace + Faiss)")

# Включаем продвинутую кластеризацию
USE_ADVANCED_CLUSTERING = True

app = FastAPI(title="Кластеризация лиц", description="API для кластеризации лиц и распределения по группам")
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# CORS middleware для поддержки фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Состояние приложения (в продакшене стоит использовать Redis/Database)
app_state = {
    "queue": [],
    "current_tasks": {},
    "task_history": []
}

# Модели данных
class FolderInfo(BaseModel):
    path: str
    name: str
    is_directory: bool
    size: Optional[int] = None
    image_count: Optional[int] = None

class QueueItem(BaseModel):
    path: str

class TaskProgress(BaseModel):
    task_id: str
    status: str  # "pending", "running", "completed", "error"
    progress: int
    message: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class ProcessingResult(BaseModel):
    moved: int
    copied: int
    clusters_count: int
    unreadable_count: int
    no_faces_count: int
    unreadable_files: List[str]
    no_faces_files: List[str]

class MoveItem(BaseModel):
    src: str
    dest: str

class ProcessCommonPhotosRequest(BaseModel):
    rootPath: str
    commonFolders: List[str]

# Утилиты
def cleanup_old_tasks():
    """Удалить старые завершенные задачи (старше 5 минут)"""
    current_time = time.time()
    tasks_to_remove = []
    
    for task_id, task in app_state["current_tasks"].items():
        if task["status"] in ["completed", "error"]:
            # Удаляем задачи старше 5 минут
            if current_time - task["created_at"] > 300:  # 5 минут
                tasks_to_remove.append(task_id)
    
    for task_id in tasks_to_remove:
        del app_state["current_tasks"][task_id]

def get_logical_drives():
    """Получить список логических дисков"""
    return [Path(p.mountpoint) for p in psutil.disk_partitions(all=False) if Path(p.mountpoint).exists()]

def get_special_dirs():
    """Получить специальные директории"""
    home = Path.home()
    return {
        "💼 Рабочий стол": home / "Desktop",
        "📄 Документы": home / "Documents", 
        "📥 Загрузки": home / "Downloads",
        "🖼 Изображения": home / "Pictures",
    }

def count_images_in_dir(path: Path) -> int:
    """Подсчитать количество изображений в директории"""
    try:
        return len([f for f in path.iterdir() if f.is_file() and f.suffix.lower() in IMG_EXTS])
    except:
        return 0

def get_folder_contents(path: Path) -> List[FolderInfo]:
    """Получить содержимое папки"""
    try:
        contents = []
        
        # Добавляем родительскую папку если не корень
        if path.parent != path:
            contents.append(FolderInfo(
                path=str(path.parent),
                name="⬅️ Назад",
                is_directory=True
            ))
        
        # Добавляем подпапки
        for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if item.is_dir():
                image_count = count_images_in_dir(item)
                contents.append(FolderInfo(
                    path=str(item),
                    name=f"📂 {item.name}",
                    is_directory=True,
                    image_count=image_count
                ))
            elif item.suffix.lower() in IMG_EXTS:
                try:
                    size = item.stat().st_size
                    contents.append(FolderInfo(
                        path=str(item),
                        name=f"🖼 {item.name}",
                        is_directory=False,
                        size=size
                    ))
                except:
                    pass
        
        return contents
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Нет доступа к папке: {path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при чтении папки: {str(e)}")

async def process_folder_task(task_id: str, folder_path: str, include_excluded: bool = False):
    loop = asyncio.get_event_loop()
    """Фоновая задача обработки папки"""
    print(f"🔍 [TASK] process_folder_task запущена: task_id={task_id}, folder_path={folder_path}, include_excluded={include_excluded}")
    
    try:
        import sys
        sys.stdout.flush()
        
        print(f"🔍 [TASK] Обновляем статус задачи {task_id} на 'running'")
        app_state["current_tasks"][task_id]["status"] = "running"
        app_state["current_tasks"][task_id]["message"] = "Начинаем обработку..."
        app_state["current_tasks"][task_id]["progress"] = 5
        
        # Небольшая задержка для демонстрации прогресс-бара
        await asyncio.sleep(2)
        app_state["current_tasks"][task_id]["progress"] = 10
        app_state["current_tasks"][task_id]["message"] = "Анализируем изображения..."
        
        await asyncio.sleep(2)
        app_state["current_tasks"][task_id]["progress"] = 25
        app_state["current_tasks"][task_id]["message"] = "Извлекаем лица..."
        
        await asyncio.sleep(2)
        app_state["current_tasks"][task_id]["progress"] = 50
        app_state["current_tasks"][task_id]["message"] = "Кластеризуем лица..."
        
        print(f"🔍 [TASK] Проверяем путь: {folder_path}")
        # Пробуем точный путь, затем ищем подходящее название в родительской папке
        import unicodedata, os
        # Unicode NFKC нормализация
        norm = unicodedata.normalize('NFKC', folder_path)
        # Пробуем прямой путь
        path = Path(norm)
        if not path.exists():
            # Определяем существующий предок
            parts = norm.split(os.sep)
            for i in range(len(parts)-1, 0, -1):
                parent = Path(os.sep.join(parts[:i]))
                if parent.exists(): break
            else:
                parent = None
            if parent and parent.exists():
                target_name = parts[-1]
                # Перебираем варианты в родительской папке
                for child in parent.iterdir():
                    # нормализуем имена
                    child_n = unicodedata.normalize('NFKC', child.name)
                    if child_n == target_name:
                        path = child
                        break
                else:
                    print(f"❌ [TASK] Не удалось найти подходящую папку в {parent}")
                    raise Exception("Путь не существует")
            else:
                print(f"❌ [TASK] Нет существующего родителя для пути {norm}")
                raise Exception("Путь не существует")
        print(f"✅ [TASK] Путь существует: {path}")
        
        # Определяем исключенные имена
        excluded_names = ["общие", "общая", "common", "shared", "все", "all", "mixed", "смешанные"]
        
        # Если не включена обработка исключенных папок, проверяем их
        if not include_excluded:
            folder_name_lower = str(path).lower()
            for excluded_name in excluded_names:
                if excluded_name in folder_name_lower:
                    raise Exception(f"Папки с названием '{excluded_name}' не обрабатываются")
        
        # Определяем тип обработки - групповая только если есть подпапки с изображениями
        subdirs_with_images = []
        for p in path.iterdir():
            if p.is_dir() and not any(excluded_name in str(p).lower() for excluded_name in excluded_names):
                # Проверяем есть ли изображения в подпапке
                has_images = any(f.suffix.lower() in IMG_EXTS for f in p.rglob("*") if f.is_file())
                if has_images:
                    subdirs_with_images.append(p)
        
        if include_excluded:
            # Всегда используем обработку общих папок, если флаг включен
            def group_progress_callback(progress_text: str, percent: int = None):
                if task_id in app_state["current_tasks"]:
                    app_state["current_tasks"][task_id]["message"] = progress_text
                    if percent is not None:
                        app_state["current_tasks"][task_id]["progress"] = percent
                    else:
                        try:
                            if "%" in progress_text:
                                match = re.search(r'(\d+)%', progress_text)
                                if match:
                                    app_state["current_tasks"][task_id]["progress"] = int(match.group(1))
                        except:
                            pass

            app_state["current_tasks"][task_id]["message"] = "Обработка общих фотографий..."
            app_state["current_tasks"][task_id]["progress"] = 10
            process_group_folder(path, progress_callback=group_progress_callback, include_excluded=True)
            result = ProcessingResult(
                moved=0, copied=0, clusters_count=0,
                unreadable_count=0, no_faces_count=0,
                unreadable_files=[], no_faces_files=[]
            )
        elif len(subdirs_with_images) > 1:
            # Групповая обработка
            def group_progress_callback(progress_text: str, percent: int = None):
                if task_id in app_state["current_tasks"]:
                    app_state["current_tasks"][task_id]["message"] = progress_text
                    if percent is not None:
                        app_state["current_tasks"][task_id]["progress"] = percent
                    else:
                        try:
                            if "%" in progress_text:
                                match = re.search(r'(\d+)%', progress_text)
                                if match:
                                    app_state["current_tasks"][task_id]["progress"] = int(match.group(1))
                        except:
                            pass
            
            app_state["current_tasks"][task_id]["message"] = "Групповая обработка папок..."
            app_state["current_tasks"][task_id]["progress"] = 10
            
            process_group_folder(path, progress_callback=group_progress_callback, include_excluded=include_excluded)
            result = ProcessingResult(
                moved=0, copied=0, clusters_count=0,
                unreadable_count=0, no_faces_count=0,
                unreadable_files=[], no_faces_files=[]
            )
        else:
            # Обычная кластеризация
            def progress_callback(progress_text: str, percent: int = None):
                if task_id in app_state["current_tasks"]:
                    app_state["current_tasks"][task_id]["message"] = progress_text
                    # Используем переданный процент или пытаемся извлечь из текста
                    if percent is not None:
                        app_state["current_tasks"][task_id]["progress"] = percent
                    else:
                        try:
                            if "%" in progress_text:
                                # Ищем число перед знаком %
                                match = re.search(r'(\d+)%', progress_text)
                                if match:
                                    app_state["current_tasks"][task_id]["progress"] = int(match.group(1))
                        except:
                            pass
            
            app_state["current_tasks"][task_id]["message"] = "Кластеризация лиц..."
            await asyncio.sleep(2)
            app_state["current_tasks"][task_id]["progress"] = 75
            
            # Выбор метода кластеризации
            if USE_ADVANCED_CLUSTERING:
                print(f"🚀 [TASK] Запускаю ADVANCED кластеризацию для {folder_path}")
                # Используем продвинутую кластеризацию
                try:
                    # Используем functools.partial для передачи параметров
                    clustering_func = functools.partial(
                        build_plan_advanced,
                        input_dir=path,
                        min_face_confidence=0.9,
                        apply_tta=True,
                        use_gpu=False,
                        progress_callback=progress_callback,
                        include_excluded=include_excluded
                    )
                    plan = await loop.run_in_executor(executor, clustering_func)
                except Exception as e:
                    print(f"⚠️ Ошибка ADVANCED кластеризации, fallback на стандартную: {e}")
                    plan = await loop.run_in_executor(
                        executor,
                        functools.partial(build_plan_advanced, path, progress_callback, include_excluded)
                    )
            else:
                print(f"🚀 [TASK] Запускаю стандартную кластеризацию для {folder_path}")
                # Стандартная кластеризация
                try:
                    plan = await loop.run_in_executor(
                        executor,
                        functools.partial(build_plan_advanced, path, progress_callback, include_excluded)
                    )
                except Exception as e:
                    app_state["current_tasks"][task_id]["status"] = "error"
                    app_state["current_tasks"][task_id]["error"] = str(e)
                    return
            
            # Проверка результата
            if not isinstance(plan, dict):
                app_state["current_tasks"][task_id]["status"] = "completed"
                app_state["current_tasks"][task_id]["progress"] = 100
                app_state["current_tasks"][task_id]["message"] = "Нет данных для обработки"
                return
            
            app_state["current_tasks"][task_id]["message"] = "Распределение по папкам..."
            app_state["current_tasks"][task_id]["progress"] = 90
            await asyncio.sleep(1)
            
            # Запуск distribute_to_folders в пуле процессов
            try:
                # Создаем callback для прогресса
                def progress_callback(progress, message):
                    if isinstance(progress, (int, float)):
                        app_state["current_tasks"][task_id]["progress"] = int(90 + progress * 0.1)
                    app_state["current_tasks"][task_id]["message"] = message
                
                moved, copied, next_cluster_id = await loop.run_in_executor(
                    executor,
                    distribute_to_folders,
                    plan,
                    Path(folder_path),
                    1,
                    progress_callback
                )
            except Exception as e:
                app_state["current_tasks"][task_id]["status"] = "error"
                app_state["current_tasks"][task_id]["error"] = str(e)
                return
            
            result = ProcessingResult(
                moved=moved,
                copied=copied, 
                clusters_count=len(plan.get("clusters", {})),
                unreadable_count=len(plan.get("unreadable", [])),
                no_faces_count=len(plan.get("no_faces", [])),
                unreadable_files=plan.get("unreadable", [])[:30],
                no_faces_files=plan.get("no_faces", [])[:30]
            )
        
        app_state["current_tasks"][task_id]["status"] = "completed"
        app_state["current_tasks"][task_id]["progress"] = 100
        app_state["current_tasks"][task_id]["message"] = "Обработка завершена"
        app_state["current_tasks"][task_id]["result"] = result.model_dump()
        
    except Exception as e:
        app_state["current_tasks"][task_id]["status"] = "error"
        app_state["current_tasks"][task_id]["error"] = str(e)
        app_state["current_tasks"][task_id]["message"] = f"Ошибка: {str(e)}"

# API endpoints
@app.get("/", response_class=HTMLResponse)
async def get_index():
    """Главная страница"""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/api/drives")
async def get_drives():
    """Получить список дисков и специальных папок"""
    drives = []
    
    # Логические диски
    for drive in get_logical_drives():
        drives.append({
            "path": str(drive),
            "name": f"📍 {drive}",
            "type": "drive"
        })
    
    # Специальные папки
    for name, path in get_special_dirs().items():
        if path.exists():
            drives.append({
                "path": str(path),
                "name": name,
                "type": "special"
            })
    
    return drives

@app.get("/api/folder")
async def get_folder_info(path: str):
    """Получить содержимое папки"""
    folder_path = Path(path)
    if not folder_path.exists():
        raise HTTPException(status_code=404, detail="Папка не найдена")
    
    contents = get_folder_contents(folder_path)
    image_count = count_images_in_dir(folder_path)
    
    return {
        "path": str(folder_path),
        "contents": contents,
        "image_count": image_count
    }

@app.post("/api/upload")
async def upload_files(
    path: str,
    files: List[UploadFile] = File(...)
):
    """Загрузить файлы в указанную папку"""
    target_dir = Path(path)
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="Целевая папка не найдена")
    
    results = []
    
    for file in files:
        try:
            if file.filename.endswith(".zip"):
                # Обработка ZIP архива
                temp_zip = target_dir / f"temp_{uuid.uuid4().hex}.zip"
                with open(temp_zip, "wb") as f:
                    content = await file.read()
                    f.write(content)
                
                with zipfile.ZipFile(temp_zip) as archive:
                    archive.extractall(target_dir)
                
                temp_zip.unlink()
                results.append({"filename": file.filename, "status": "extracted"})
            else:
                # Обычный файл
                file_path = target_dir / file.filename
                with open(file_path, "wb") as f:
                    content = await file.read()
                    f.write(content)
                results.append({"filename": file.filename, "status": "uploaded"})
                
        except Exception as e:
            results.append({"filename": file.filename, "status": "error", "error": str(e)})
    
    return {"results": results}

@app.get("/api/queue")
async def get_queue():
    """Получить текущую очередь обработки"""
    return {"queue": app_state["queue"]}

@app.post("/api/queue/add")
async def add_to_queue(item: QueueItem, includeExcluded: bool = False):
    """Добавить папку в очередь"""
    print(f"🔍 [API] add_to_queue вызван: path={item.path}, includeExcluded={includeExcluded}")
    
    # Проверяем, что папка не содержит исключаемые названия, если не разрешено включать общие
    if not includeExcluded:
        print("🔍 [API] Проверяем исключенные папки...")
        excluded_names = ["общие", "общая", "common", "shared", "все", "all", "mixed", "смешанные"]
        folder_name_lower = str(item.path).lower()
        for excluded_name in excluded_names:
            if excluded_name in folder_name_lower:
                print(f"❌ [API] Папка исключена: {excluded_name} в {folder_name_lower}")
                raise HTTPException(status_code=400, detail=f"Папки с названием '{excluded_name}' не обрабатываются")
        print("✅ [API] Папка не исключена")
    
    print(f"🔍 [API] Текущая очередь: {app_state['queue']}")
    
    if item.path not in app_state["queue"]:
        app_state["queue"].append(item.path)
        print(f"✅ [API] Папка добавлена в очередь: {item.path}")
        print(f"🔍 [API] Новая очередь: {app_state['queue']}")
        return {"message": f"Папка добавлена в очередь: {item.path}"}
    else:
        print(f"⚠️ [API] Папка уже в очереди: {item.path}")
        return {"message": "Папка уже в очереди"}

@app.delete("/api/queue")
async def clear_queue():
    """Очистить очередь"""
    app_state["queue"].clear()
    return {"message": "Очередь очищена"}

@app.post("/api/process")
async def process_queue(background_tasks: BackgroundTasks, includeExcluded: bool = False):
    """Запустить обработку очереди"""
    print(f"🔍 [API] process_queue вызван: includeExcluded={includeExcluded}")
    print(f"🔍 [API] Текущая очередь: {app_state['queue']}")
    
    if not app_state["queue"]:
        print("❌ [API] Очередь пуста")
        raise HTTPException(status_code=400, detail="Очередь пуста")
    
    task_ids = []
    print(f"🔍 [API] Создаем задачи для {len(app_state['queue'])} папок")
    
    for folder_path in app_state["queue"]:
        task_id = str(uuid.uuid4())
        print(f"🔍 [API] Создаем задачу {task_id} для папки: {folder_path}")
        
        app_state["current_tasks"][task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "message": "В очереди...",
            "folder_path": folder_path,
            "created_at": time.time(),
            "include_excluded": includeExcluded
        }
        
        print(f"🔍 [API] Добавляем фоновую задачу: {task_id}")
        background_tasks.add_task(process_folder_task, task_id, folder_path, includeExcluded)
        task_ids.append(task_id)
    
    print(f"🔍 [API] Очищаем очередь, создано {len(task_ids)} задач")
    app_state["queue"].clear()
    
    result = {"message": "Обработка запущена", "task_ids": task_ids}
    print(f"✅ [API] Возвращаем результат: {result}")
    return result

@app.get("/api/tasks")
async def get_tasks():
    """Получить статус всех задач"""
    # Очищаем старые задачи
    cleanup_old_tasks()
    
    # Возвращаем все задачи (включая недавно завершенные)
    return {"tasks": list(app_state["current_tasks"].values())}

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """Получить статус конкретной задачи"""
    if task_id not in app_state["current_tasks"]:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    
    return app_state["current_tasks"][task_id]

@app.post("/api/tasks/clear")
async def clear_completed_tasks():
    """Очистить все завершенные задачи"""
    tasks_to_remove = []
    
    for task_id, task in app_state["current_tasks"].items():
        if task["status"] in ["completed", "error"]:
            tasks_to_remove.append(task_id)
    
    for task_id in tasks_to_remove:
        del app_state["current_tasks"][task_id]
    
    return {"message": f"Очищено {len(tasks_to_remove)} завершенных задач"}

@app.get("/api/image/preview")
async def get_image_preview(path: str, size: int = 150):
    """Получить превью изображения"""
    img_path = Path(path)
    if not img_path.exists() or img_path.suffix.lower() not in IMG_EXTS:
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    
    try:
        # Создаем превью в памяти
        with Image.open(img_path) as img:
            img = img.convert("RGB")
            img = ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            buf.seek(0)
            from fastapi.responses import StreamingResponse
            return StreamingResponse(buf, media_type="image/jpeg")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка создания превью: {str(e)}")

@app.get("/api/zip")
async def zip_folder(path: str):
    """Создает ZIP архивацию указанной папки и возвращает файл"""
    folder = Path(path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=404, detail="Папка не найдена")
    # Создаем временный zip-файл
    tmp_dir = tempfile.gettempdir()
    zip_name = f"{uuid.uuid4()}.zip"
    zip_path = Path(tmp_dir) / zip_name
    # Делает архив
    shutil.make_archive(str(zip_path.with_suffix('')), 'zip', root_dir=folder)
    # Отдает файл для скачивания
    return FileResponse(str(zip_path), media_type="application/zip", filename=f"{folder.name}.zip")

# Add SSE endpoint for streaming tasks
@app.get("/api/stream/tasks")
async def stream_tasks():
    """Stream all task updates via Server-Sent Events"""
    async def event_generator():
        while True:
            # Очищаем старые задачи
            cleanup_old_tasks()
            
            # Получаем только активные задачи (pending, running)
            active_tasks = [
                task for task in app_state["current_tasks"].values() 
                if task["status"] in ["pending", "running"]
            ]
            
            data = {"tasks": active_tasks}
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Статические файлы
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/api/move")
async def move_item(srcPath: str = Query(...), destPath: str = Query(...)):
    """Переместить файл или папку"""
    src_path = Path(srcPath)
    dest_path = Path(destPath)
    
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="Источник не найден")
    
    try:
        # Определяем целевой путь
        if dest_path.exists():
            if dest_path.is_dir():
                # Если destination - существующая папка
                target = dest_path / src_path.name
            else:
                # Если destination - существующий файл, используем родительскую папку
                target = dest_path.parent / src_path.name
        else:
            # Если destination не существует, создаем его как папку
            dest_path.mkdir(parents=True, exist_ok=True)
            target = dest_path / src_path.name
        
        # Проверяем, не пытаемся ли переместить файл на самого себя
        if src_path.resolve() == target.resolve():
            return {"message": "Файл уже находится в целевой папке", "src": str(src_path), "dest": str(target)}
        
        # Если целевой файл уже существует, добавляем суффикс
        if target.exists():
            base_name = target.stem
            extension = target.suffix
            counter = 1
            while target.exists():
                target = target.parent / f"{base_name}_{counter}{extension}"
                counter += 1
        
        # Перемещаем файл
        shutil.move(str(src_path), str(target))
        return {"message": f"✅ Файл перемещен: {src_path.name}", "src": str(src_path), "dest": str(target)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка перемещения: {str(e)}")

@app.post("/api/create-folder")
async def create_folder(path: str = Query(...), name: str = Query(...)):
    """Создать новую папку"""
    parent_path = Path(path)
    
    if not parent_path.exists() or not parent_path.is_dir():
        raise HTTPException(status_code=404, detail="Родительская папка не найдена")
    
    new_folder = parent_path / name
    
    if new_folder.exists():
        raise HTTPException(status_code=400, detail="Папка с таким именем уже существует")
    
    try:
        new_folder.mkdir(parents=False, exist_ok=False)
        return {"message": f"✅ Папка '{name}' создана", "path": str(new_folder)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка создания папки: {str(e)}")

@app.post("/api/create-file")
async def create_file(path: str = Query(...), name: str = Query(...)):
    """Создать новый файл"""
    parent_path = Path(path)
    
    if not parent_path.exists() or not parent_path.is_dir():
        raise HTTPException(status_code=404, detail="Родительская папка не найдена")
    
    new_file = parent_path / name
    
    if new_file.exists():
        raise HTTPException(status_code=400, detail="Файл с таким именем уже существует")
    
    try:
        new_file.touch()
        return {"message": f"✅ Файл '{name}' создан", "path": str(new_file)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка создания файла: {str(e)}")

@app.post("/api/rename")
async def rename_item(oldPath: str = Query(...), newName: str = Query(...)):
    """Переименовать файл или папку"""
    old_path = Path(oldPath)
    
    if not old_path.exists():
        raise HTTPException(status_code=404, detail="Файл или папка не найдена")
    
    new_path = old_path.parent / newName
    
    if new_path.exists():
        raise HTTPException(status_code=400, detail="Файл или папка с таким именем уже существует")
    
    try:
        old_path.rename(new_path)
        return {"message": f"✅ Переименовано в '{newName}'", "oldPath": str(old_path), "newPath": str(new_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка переименования: {str(e)}")

@app.delete("/api/delete")
async def delete_item(path: str = Query(...)):
    """Удалить файл или папку"""
    item_path = Path(path)
    
    if not item_path.exists():
        raise HTTPException(status_code=404, detail="Файл или папка не найдена")
    
    try:
        if item_path.is_dir():
            shutil.rmtree(item_path)
            return {"message": f"✅ Папка '{item_path.name}' удалена", "path": str(item_path)}
        else:
            item_path.unlink()
            return {"message": f"✅ Файл '{item_path.name}' удален", "path": str(item_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка удаления: {str(e)}")

@app.post("/api/process-common-photos")
async def process_common_photos(request: ProcessCommonPhotosRequest):
    """Специальный алгоритм для обработки общих фотографий"""
    try:
        root_path = request.rootPath
        common_folders = request.commonFolders
        
        if not root_path:
            raise HTTPException(status_code=400, detail="Не указан корневой путь")
        
        if not common_folders:
            raise HTTPException(status_code=400, detail="Не найдены общие папки")
        
        print(f"🔍 [API] Обработка общих фотографий: {len(common_folders)} папок")
        
        # Собираем все уникальные кластеры из всех общих папок
        all_unique_clusters = set()
        processed_folders = 0
        
        for common_folder in common_folders:
            try:
                print(f"🔍 [API] Обрабатываем папку: {common_folder}")
                
                # Проверяем, что папка существует
                folder_path = Path(common_folder)
                if not folder_path.exists():
                    print(f"⚠️ [API] Папка не существует: {common_folder}")
                    continue
                
                # Проверяем, что в папке есть изображения
                image_files = list(folder_path.glob("*.jpg")) + list(folder_path.glob("*.jpeg")) + list(folder_path.glob("*.png"))
                if not image_files:
                    print(f"⚠️ [API] В папке нет изображений: {common_folder}")
                    continue
                
                print(f"📸 [API] Найдено изображений: {len(image_files)}")
                
                # Кластеризуем общую папку
                plan = build_plan_advanced(
                    input_dir=folder_path,
                    progress_callback=None,
                    sim_threshold=0.60,
                    min_cluster_size=2,
                    ctx_id=0,
                    det_size=(640, 640)
                )
                
                print(f"📊 [API] Результат кластеризации: {type(plan)}")
                if isinstance(plan, dict):
                    print(f"📊 [API] Ключи результата: {list(plan.keys())}")
                
                # Собираем уникальные кластеры
                clusters_found = 0
                if isinstance(plan, dict) and "clusters" in plan:
                    clusters_found = len(plan["clusters"])
                    for cluster_id in plan["clusters"].keys():
                        all_unique_clusters.add(int(cluster_id))
                elif isinstance(plan, dict) and "clusters_count" in plan:
                    clusters_found = plan["clusters_count"]
                    # Если есть clusters_count, создаем фиктивные кластеры
                    for i in range(clusters_found):
                        all_unique_clusters.add(i + 1)
                
                processed_folders += 1
                print(f"✅ [API] Обработана папка {common_folder}, найдено кластеров: {clusters_found}")
                
            except Exception as e:
                print(f"⚠️ [API] Ошибка обработки папки {common_folder}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # Создаем пустые папки для каждого уникального человека
        root_dir = Path(root_path)
        created_folders = []
        
        for i, cluster_id in enumerate(sorted(all_unique_clusters), 1):
            folder_name = str(i)
            folder_path = root_dir / folder_name
            folder_path.mkdir(parents=True, exist_ok=True)
            created_folders.append(folder_name)
            print(f"📁 [API] Создана папка: {folder_path}")
        
        result = {
            "success": True,
            "processed_folders": processed_folders,
            "unique_people": len(all_unique_clusters),
            "created_folders": created_folders,
            "message": f"Обработано {processed_folders} общих папок, создано {len(all_unique_clusters)} папок для уникальных людей"
        }
        
        print(f"✅ [API] Обработка завершена: {result}")
        return result
        
    except Exception as e:
        print(f"❌ [API] Ошибка обработки общих фотографий: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка обработки общих фотографий: {str(e)}")

@app.get("/favicon.ico")
async def favicon():
    """Возвращает простой favicon чтобы избежать 404 ошибок"""
    return Response(content="", media_type="image/x-icon")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
