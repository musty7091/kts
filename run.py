# C:\kts\run.py

import os

from app import create_app # app paketimizdeki __init__.py'den create_app fonksiyonunu import et

app = create_app()

if __name__ == '__main__':
    # Flask CLI komutlarını (flask create-tables, flask init-data) 
    # çalıştırabilmek için bu dosyanın doğru şekilde ayarlanmış olması önemlidir.
    # FLASK_APP=run.py veya FLASK_APP=app (eğer __init__.py içinde app doğrudan oluşturuluyorsa)
    # ortam değişkeni ayarlanabilir. Biz create_app kullandığımız için FLASK_APP=run:app gibi
    # bir yapı da gerekebilir, ama genellikle Flask run.py'yi bulur.
    #
    # Eğer `flask` komutları "Could not locate a Flask application" hatası verirse,
    # komut satırında şu komutu çalıştırın:
    # PowerShell için: $env:FLASK_APP = "run.py" (veya $env:FLASK_APP = "app:create_app()")
    # CMD için: set FLASK_APP=run.py (veya set FLASK_APP=app:create_app())
    #
    # Debug artık varsayılan olarak kapalıdır.
    # Geliştirme için açmak istersen:
    # PowerShell: $env:FLASK_DEBUG="1"
    # CMD: set FLASK_DEBUG=1
    debug_mode = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
    app.run(debug=debug_mode)