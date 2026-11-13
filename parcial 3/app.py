from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, Response
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path
from functools import wraps
from datetime import datetime
from threading import RLock
import secrets
import json
import os
import csv
import io

# =====================================================
# CONFIGURACION DE LA APLICACION
# =====================================================
app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
DATOS_DIR = BASE_DIR / 'datos'
DATOS_DIR.mkdir(exist_ok=True)
CLAVE_FILE = DATOS_DIR / '.clave_sesion'
if not CLAVE_FILE.exists():
    CLAVE_FILE.write_text(secrets.token_hex(32), encoding='utf-8')
app.secret_key = CLAVE_FILE.read_text(encoding='utf-8').strip()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
BLOQUEO = RLock()

# =====================================================
# ARCHIVOS JSON
# =====================================================
USUARIOS_FILE = DATOS_DIR / 'usuarios.json'
PIEZAS_FILE = DATOS_DIR / 'piezas.json'
SOLICITUDES_FILE = DATOS_DIR / 'solicitudes.json'
MOVIMIENTOS_FILE = DATOS_DIR / 'movimientos.json'


def cargar_datos(archivo):
    if not archivo.exists():
        return []
    with open(archivo, 'r', encoding='utf-8') as f:
        return json.load(f)


def guardar_datos(archivo, datos):
    temporal = archivo.with_suffix('.tmp')
    with open(temporal, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)
    os.replace(temporal, archivo)


def siguiente_id(registros):
    return max((registro['id'] for registro in registros), default=0) + 1


def fecha_actual():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# =====================================================
# DATOS DE DEMOSTRACION
# =====================================================
def inicializar_datos():
    if not USUARIOS_FILE.exists():
        usuarios = [
            {'id': 1, 'nombre': 'Administrador principal', 'usuario': 'admin', 'clave': generate_password_hash('Admin123!'), 'rol': 'administrador'},
            {'id': 2, 'nombre': 'Gerente de almacén', 'usuario': 'gerente', 'clave': generate_password_hash('Gerente123!'), 'rol': 'gerente'},
            {'id': 3, 'nombre': 'Técnico de mantenimiento', 'usuario': 'tecnico', 'clave': generate_password_hash('Tecnico123!'), 'rol': 'tecnico'}
        ]
        guardar_datos(USUARIOS_FILE, usuarios)
    if not PIEZAS_FILE.exists():
        datos = [
            ('IND-001','Rodamiento 6205','Rodamientos',24,'A1-01',5),
            ('IND-002','Rodamiento 6308','Rodamientos',12,'A1-02',5),
            ('IND-003','Banda trapezoidal A-42','Transmisión',18,'A2-01',4),
            ('IND-004','Cadena industrial 08B','Transmisión',7,'A2-02',4),
            ('IND-005','Polea de aluminio 120 mm','Transmisión',9,'A2-03',3),
            ('IND-006','Engrane recto 24 dientes','Transmisión',5,'A2-04',3),
            ('IND-007','Motor eléctrico 1 HP','Motores',3,'B1-01',2),
            ('IND-008','Motor eléctrico 3 HP','Motores',2,'B1-02',2),
            ('IND-009','Contactor trifásico 25 A','Eléctrico',16,'B2-01',5),
            ('IND-010','Relevador térmico 12 A','Eléctrico',4,'B2-02',5),
            ('IND-011','Interruptor termomagnético','Eléctrico',10,'B2-03',3),
            ('IND-012','Sensor inductivo M12','Sensores',6,'C1-01',4),
            ('IND-013','Sensor fotoeléctrico','Sensores',8,'C1-02',3),
            ('IND-014','Válvula neumática 5/2','Neumática',11,'C2-01',4),
            ('IND-015','Cilindro neumático 32 mm','Neumática',5,'C2-02',2),
            ('IND-016','Manguera neumática 8 mm','Neumática',30,'C2-03',8),
            ('IND-017','Filtro hidráulico 10 micras','Hidráulica',3,'D1-01',4),
            ('IND-018','Bomba hidráulica 5 L/min','Hidráulica',1,'D1-02',2),
            ('IND-019','Sello mecánico 25 mm','Sellos',0,'D2-01',3),
            ('IND-020','Junta de caucho industrial','Sellos',45,'D2-02',10)
        ]
        piezas = [{'id': i, 'codigo': codigo, 'nombre': nombre, 'categoria': categoria, 'cantidad': cantidad, 'ubicacion': ubicacion, 'minimo': minimo} for i, (codigo,nombre,categoria,cantidad,ubicacion,minimo) in enumerate(datos,1)]
        guardar_datos(PIEZAS_FILE, piezas)
    for archivo in (SOLICITUDES_FILE, MOVIMIENTOS_FILE):
        if not archivo.exists():
            guardar_datos(archivo, [])


inicializar_datos()

# =====================================================
# SEGURIDAD Y CONTROL DE PERMISOS
# =====================================================
def usuario_actual():
    uid = session.get('usuario_id')
    return next((u for u in cargar_datos(USUARIOS_FILE) if u['id'] == uid), None)


def acceso_requerido(*roles):
    def decorador(funcion):
        @wraps(funcion)
        def protegida(*args, **kwargs):
            usuario = usuario_actual()
            if not usuario:
                session.clear()
                return redirect(url_for('login'))
            if roles and usuario['rol'] not in roles:
                abort(403)
            return funcion(*args, **kwargs)
        return protegida
    return decorador


@app.before_request
def comprobar_formularios():
    if request.method == 'POST':
        token = session.get('csrf_token')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400, description='Formulario no válido. Actualiza la página e inténtalo de nuevo.')


@app.context_processor
def variables_comunes():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(24)
    return {'actual': usuario_actual(), 'csrf_token': session['csrf_token']}


def numero_entero(valor, minimo=0):
    try:
        numero = int(valor)
        if numero < minimo:
            return None
        return numero
    except (TypeError, ValueError):
        return None


def buscar_por_id(registros, identificador):
    return next((r for r in registros if r['id'] == identificador), None)


def registrar_movimiento(movimientos, pieza, tipo, cantidad, responsable, detalle):
    movimientos.append({'id': siguiente_id(movimientos), 'fecha': fecha_actual(), 'pieza_id': pieza['id'], 'codigo': pieza['codigo'], 'pieza': pieza['nombre'], 'tipo': tipo, 'cantidad': cantidad, 'responsable': responsable, 'detalle': detalle})


# =====================================================
# INICIO Y CIERRE DE SESION
# =====================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if usuario_actual():
        return redirect(url_for('index'))
    if request.method == 'POST':
        nombre = request.form.get('username', '').strip()
        clave = request.form.get('password', '')
        usuario = next((u for u in cargar_datos(USUARIOS_FILE) if u['usuario'] == nombre), None)
        if usuario and check_password_hash(usuario['clave'], clave):
            session.clear()
            session['usuario_id'] = usuario['id']
            session['csrf_token'] = secrets.token_hex(24)
            return redirect(url_for('index'))
        flash('Usuario o contraseña incorrectos.', 'error')
    return render_template('login.html')


@app.route('/logout', methods=['POST'])
@acceso_requerido()
def logout():
    session.clear()
    return redirect(url_for('login'))


# =====================================================
# DASHBOARD Y BUSQUEDA
# =====================================================
@app.route('/')
@acceso_requerido()
def index():
    piezas = cargar_datos(PIEZAS_FILE)
    solicitudes = cargar_datos(SOLICITUDES_FILE)
    movimientos = cargar_datos(MOVIMIENTOS_FILE)
    rol = usuario_actual()['rol']
    if rol == 'tecnico':
        solicitudes_visibles = [s for s in solicitudes if s['tecnico_id'] == usuario_actual()['id']]
    else:
        solicitudes_visibles = solicitudes
    busqueda = request.args.get('q', '').strip().lower()
    if busqueda:
        piezas_filtradas = [p for p in piezas if any(busqueda in str(p[k]).lower() for k in ('codigo','nombre','categoria','ubicacion'))]
    else:
        piezas_filtradas = piezas
    return render_template('index.html', piezas=piezas_filtradas,
        solicitudes=sorted(solicitudes_visibles, key=lambda s:s['id'], reverse=True),
        movimientos=sorted(movimientos, key=lambda m:m['id'], reverse=True),
        usuarios=cargar_datos(USUARIOS_FILE) if rol == 'administrador' else [],
        total_piezas=len(piezas), existencias=sum(p['cantidad'] for p in piezas),
        bajas=sum(p['cantidad'] > 0 and p['cantidad'] <= p['minimo'] for p in piezas),
        agotadas=sum(p['cantidad'] == 0 for p in piezas),
        pendientes=sum(s['estado'] == 'Pendiente' for s in solicitudes),
        busqueda=request.args.get('q',''), pestana=request.args.get('tab','resumen'))


# =====================================================
# PIEZAS: ADMINISTRADOR
# =====================================================
@app.route('/piezas/nueva', methods=['POST'])
@acceso_requerido('administrador')
def nueva_pieza():
    codigo = request.form.get('codigo','').strip().upper()
    nombre = request.form.get('nombre','').strip()
    categoria = request.form.get('categoria','').strip()
    ubicacion = request.form.get('ubicacion','').strip()
    cantidad = numero_entero(request.form.get('cantidad'))
    minimo = numero_entero(request.form.get('minimo'))
    with BLOQUEO:
        piezas = cargar_datos(PIEZAS_FILE)
        if not all((codigo,nombre,categoria,ubicacion)) or cantidad is None or minimo is None:
            flash('Completa correctamente los datos de la pieza.', 'error')
        elif any(p['codigo'] == codigo for p in piezas):
            flash('Ya existe una pieza con ese código.', 'error')
        else:
            pieza = {'id':siguiente_id(piezas),'codigo':codigo,'nombre':nombre,'categoria':categoria,'cantidad':cantidad,'ubicacion':ubicacion,'minimo':minimo}
            piezas.append(pieza)
            guardar_datos(PIEZAS_FILE, piezas)
            if cantidad:
                movimientos = cargar_datos(MOVIMIENTOS_FILE)
                registrar_movimiento(movimientos, pieza, 'Entrada', cantidad, usuario_actual()['nombre'], 'Registro inicial de pieza')
                guardar_datos(MOVIMIENTOS_FILE, movimientos)
            flash('Pieza registrada correctamente.', 'ok')
    return redirect(url_for('index', tab='piezas'))


@app.route('/piezas/<int:pid>/editar', methods=['POST'])
@acceso_requerido('administrador')
def editar_pieza(pid):
    with BLOQUEO:
        piezas = cargar_datos(PIEZAS_FILE)
        pieza = buscar_por_id(piezas,pid)
        if not pieza:
            abort(404)
        codigo = request.form.get('codigo','').strip().upper()
        nombre = request.form.get('nombre','').strip()
        categoria = request.form.get('categoria','').strip()
        ubicacion = request.form.get('ubicacion','').strip()
        minimo = numero_entero(request.form.get('minimo'))
        if not all((codigo,nombre,categoria,ubicacion)) or minimo is None or any(p['codigo']==codigo and p['id']!=pid for p in piezas):
            flash('Datos incompletos o código duplicado.', 'error')
        else:
            pieza.update({'codigo':codigo,'nombre':nombre,'categoria':categoria,'ubicacion':ubicacion,'minimo':minimo})
            guardar_datos(PIEZAS_FILE,piezas)
            flash('Datos actualizados.', 'ok')
    return redirect(url_for('index',tab='piezas'))


@app.route('/piezas/<int:pid>/eliminar', methods=['POST'])
@acceso_requerido('administrador')
def eliminar_pieza(pid):
    with BLOQUEO:
        piezas = cargar_datos(PIEZAS_FILE)
        pieza = buscar_por_id(piezas,pid)
        if not pieza:
            abort(404)
        solicitudes = cargar_datos(SOLICITUDES_FILE)
        if any(s['pieza_id']==pid for s in solicitudes):
            flash('No puedes eliminar una pieza que tenga solicitudes: se conserva su historial.', 'error')
        else:
            guardar_datos(PIEZAS_FILE,[p for p in piezas if p['id']!=pid])
            flash('Pieza eliminada.', 'ok')
    return redirect(url_for('index',tab='piezas'))


@app.route('/piezas/<int:pid>/entrada', methods=['POST'])
@acceso_requerido('administrador')
def entrada_pieza(pid):
    cantidad = numero_entero(request.form.get('cantidad'),1)
    if cantidad is None:
        flash('La cantidad debe ser mayor que cero.', 'error')
        return redirect(url_for('index',tab='piezas'))
    with BLOQUEO:
        piezas = cargar_datos(PIEZAS_FILE)
        pieza = buscar_por_id(piezas,pid)
        if not pieza:
            abort(404)
        pieza['cantidad'] += cantidad
        movimientos = cargar_datos(MOVIMIENTOS_FILE)
        registrar_movimiento(movimientos, pieza, 'Entrada', cantidad, usuario_actual()['nombre'], 'Reposición de almacén')
        guardar_datos(PIEZAS_FILE,piezas)
        guardar_datos(MOVIMIENTOS_FILE,movimientos)
    flash('Entrada registrada y existencias actualizadas.', 'ok')
    return redirect(url_for('index',tab='piezas'))


# =====================================================
# SOLICITUDES: TECNICO
# =====================================================
@app.route('/solicitudes/nueva', methods=['POST'])
@acceso_requerido('tecnico')
def nueva_solicitud():
    pid = numero_entero(request.form.get('pieza_id'),1)
    cantidad = numero_entero(request.form.get('cantidad'),1)
    motivo = request.form.get('motivo','').strip()
    with BLOQUEO:
        piezas = cargar_datos(PIEZAS_FILE)
        pieza = buscar_por_id(piezas,pid)
        if not pieza or cantidad is None or not motivo:
            flash('Selecciona una pieza, una cantidad válida y el motivo.', 'error')
        elif cantidad > pieza['cantidad']:
            flash('La cantidad solicitada supera las existencias actuales.', 'error')
        else:
            solicitudes = cargar_datos(SOLICITUDES_FILE)
            solicitudes.append({'id':siguiente_id(solicitudes),'fecha':fecha_actual(),
                'tecnico_id':usuario_actual()['id'],'tecnico':usuario_actual()['nombre'],
                'pieza_id':pieza['id'],'codigo':pieza['codigo'],'pieza':pieza['nombre'],
                'cantidad':cantidad,'motivo':motivo,'estado':'Pendiente',
                'gerente':'','fecha_respuesta':''})
            guardar_datos(SOLICITUDES_FILE,solicitudes)
            flash('Solicitud enviada al gerente.', 'ok')
    return redirect(url_for('index',tab='solicitudes'))


# =====================================================
# APROBAR / RECHAZAR: GERENTE
# =====================================================
@app.route('/solicitudes/<int:sid>/resolver', methods=['POST'])
@acceso_requerido('gerente')
def resolver_solicitud(sid):
    decision = request.form.get('decision','')
    if decision not in ('aprobar','rechazar'):
        abort(400)
    with BLOQUEO:
        solicitudes = cargar_datos(SOLICITUDES_FILE)
        solicitud = buscar_por_id(solicitudes,sid)
        if not solicitud:
            abort(404)
        if solicitud['estado'] != 'Pendiente':
            flash('Esta solicitud ya fue atendida.', 'error')
        elif decision == 'rechazar':
            solicitud['estado'] = 'Rechazada'
            solicitud['gerente'] = usuario_actual()['nombre']
            solicitud['fecha_respuesta'] = fecha_actual()
            guardar_datos(SOLICITUDES_FILE,solicitudes)
            flash('Solicitud rechazada. Las existencias no cambiaron.', 'ok')
        else:
            piezas = cargar_datos(PIEZAS_FILE)
            pieza = buscar_por_id(piezas,solicitud['pieza_id'])
            if not pieza or solicitud['cantidad'] > pieza['cantidad']:
                flash('No hay existencias suficientes para aprobar la solicitud.', 'error')
            else:
                pieza['cantidad'] -= solicitud['cantidad']
                solicitud['estado'] = 'Aprobada'
                solicitud['gerente'] = usuario_actual()['nombre']
                solicitud['fecha_respuesta'] = fecha_actual()
                movimientos = cargar_datos(MOVIMIENTOS_FILE)
                registrar_movimiento(movimientos,pieza,'Salida',solicitud['cantidad'],usuario_actual()['nombre'], 'Solicitud #'+str(sid)+' de '+solicitud['tecnico'])
                guardar_datos(PIEZAS_FILE,piezas)
                guardar_datos(MOVIMIENTOS_FILE,movimientos)
                guardar_datos(SOLICITUDES_FILE,solicitudes)
                flash('Solicitud aprobada; inventario y movimientos actualizados.', 'ok')
    return redirect(url_for('index',tab='solicitudes'))


# =====================================================
# USUARIOS: ADMINISTRADOR
# =====================================================
@app.route('/usuarios/nuevo', methods=['POST'])
@acceso_requerido('administrador')
def nuevo_usuario():
    nombre = request.form.get('nombre','').strip()
    cuenta = request.form.get('usuario','').strip()
    clave = request.form.get('clave','')
    rol = request.form.get('rol','')
    with BLOQUEO:
        usuarios = cargar_datos(USUARIOS_FILE)
        if not nombre or not cuenta or len(clave)<8 or rol not in ('administrador','gerente','tecnico'):
            flash('Completa los datos y usa una contraseña de al menos 8 caracteres.', 'error')
        elif any(u['usuario']==cuenta for u in usuarios):
            flash('El nombre de usuario ya está ocupado.', 'error')
        else:
            usuarios.append({'id':siguiente_id(usuarios),'nombre':nombre,'usuario':cuenta,'clave':generate_password_hash(clave),'rol':rol})
            guardar_datos(USUARIOS_FILE,usuarios)
            flash('Usuario registrado correctamente.', 'ok')
    return redirect(url_for('index',tab='usuarios'))


@app.route('/usuarios/<int:uid>/eliminar', methods=['POST'])
@acceso_requerido('administrador')
def eliminar_usuario(uid):
    with BLOQUEO:
        usuarios = cargar_datos(USUARIOS_FILE)
        objetivo = buscar_por_id(usuarios,uid)
        if not objetivo:
            abort(404)
        if uid == usuario_actual()['id']:
            flash('No puedes eliminar tu propia cuenta.', 'error')
        elif objetivo['rol']=='administrador' and sum(u['rol']=='administrador' for u in usuarios)==1:
            flash('Debe conservarse al menos un administrador.', 'error')
        elif any(s['tecnico_id']==uid and s['estado']=='Pendiente' for s in cargar_datos(SOLICITUDES_FILE)):
            flash('No se puede eliminar un técnico con solicitudes pendientes.', 'error')
        else:
            guardar_datos(USUARIOS_FILE,[u for u in usuarios if u['id']!=uid])
            flash('Usuario eliminado; los historiales existentes se conservan.', 'ok')
    return redirect(url_for('index',tab='usuarios'))


# =====================================================
# REPORTES CSV: GERENTE
# =====================================================
@app.route('/reportes/<tipo>')
@acceso_requerido('gerente')
def descargar_reporte(tipo):
    if tipo == 'inventario':
        encabezados = ['Código','Pieza','Categoría','Cantidad','Ubicación','Mínimo','Estado']
        filas = [[p['codigo'],p['nombre'],p['categoria'],p['cantidad'],p['ubicacion'],p['minimo'], 'Agotada' if p['cantidad']==0 else 'Baja' if p['cantidad']<=p['minimo'] else 'Normal'] for p in cargar_datos(PIEZAS_FILE)]
    elif tipo == 'solicitudes':
        encabezados = ['ID','Fecha','Técnico','Código','Pieza','Cantidad','Motivo','Estado','Gerente','Fecha de respuesta']
        filas = [[s[k] for k in ('id','fecha','tecnico','codigo','pieza','cantidad','motivo','estado','gerente','fecha_respuesta')] for s in cargar_datos(SOLICITUDES_FILE)]
    elif tipo == 'movimientos':
        encabezados = ['ID','Fecha','Código','Pieza','Tipo','Cantidad','Responsable','Detalle']
        filas = [[m[k] for k in ('id','fecha','codigo','pieza','tipo','cantidad','responsable','detalle')] for m in cargar_datos(MOVIMIENTOS_FILE)]
    else:
        abort(404)
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(encabezados)
    escritor.writerows(filas)
    return Response('\ufeff'+salida.getvalue(), mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename=reporte_{tipo}.csv'})


if __name__ == '__main__':
    app.run(debug=True)
