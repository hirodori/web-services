import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sse import sse
import sqlite3
from sqlite3 import Error

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding

# Criação da chave privada
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)
# Criação da chave pública
public_key = private_key.public_key()

# Conversão das chaves em formato PEM
private_key_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)
public_key_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)

# Chave pública é salva em um arquivo PEM
with open('public_key.pem', 'wb') as public_file:
    public_file.write(public_key_pem)

app = Flask(__name__)
app.config["REDIS_URL"] = "redis://localhost:6379/0"
app.register_blueprint(sse, url_prefix='/stream')
CORS(app)

DATABASE = 'tasks.db'

# Conexão com o banco de dados
def create_connection():
    conn = None
    try:
        conn = sqlite3.connect(DATABASE)
    except Error as e:
        print(e)
    return conn

# Função para criar a tabela do banco de dados
def create_table():
    conn = create_connection()
    try:
        sql = '''CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    importance INTEGER CHECK(importance >= 1 AND importance <= 5),
                    category TEXT,
                    deadline DATE
                );'''
        conn.execute(sql)
        conn.commit()
    except Error as e:
        print(e)
    finally:
        if conn:
            conn.close()

# Função para assinatura de uma mensagem
def sign_message(message, private_key):
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return signature

# Função para verificação de autenticação de uma mensagem
def verify_signature(message, signature, public_key):
    try:
        public_key.verify(
            signature,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return True
    except:
        return False

# Função para retornar todas as tarefas armazenadas no banco de dados
@app.route('/tasks', methods=['GET'])
def get_tasks():
    conn = create_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks")
    rows = cur.fetchall()
    tasks = []
    for row in rows:
        task = {
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'importance': row[3],
            'category': row[4],
            'deadline': row[5]
        }
        tasks.append(task)
    conn.close()
    sse.publish({"event": "GET"}, type='show')
    signature = sign_message(json.dumps(tasks).encode(), private_key)
    with open('public_key.pem', 'rb') as public_file:
        public_key_pem = public_file.read()
        publicKey = serialization.load_pem_public_key(public_key_pem)
    verified_signature = verify_signature(json.dumps(tasks).encode(), signature, publicKey)
    if (verified_signature):
        print('Signature was verified!')
    else: 
        print('Signature was not verified!')
    
    return jsonify(tasks)

# Função para criar uma tarefa nova no banco de dados
@app.route('/tasks', methods=['POST'])
def create_task():
    task = request.get_json()
    conn = create_connection()
    sql = '''INSERT INTO tasks(name, description, importance, category, deadline)
             VALUES(?,?,?,?,?)'''
    cur = conn.cursor()
    cur.execute(sql, (task['name'], task['description'], task['importance'], task['category'], task['deadline']))
    conn.commit()
    task_id = cur.lastrowid
    conn.close()
    sse.publish({"event": "POST"}, type='create')
    return jsonify({'id': task_id}), 201

# Função para atualizar uma tarefa no banco de dados
@app.route('/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    task = request.get_json()
    conn = create_connection()
    sql = '''UPDATE tasks
             SET name = ?,
                 description = ?,
                 importance = ?,
                 category = ?,
                 deadline = ?
             WHERE id = ?'''
    cur = conn.cursor()
    cur.execute(sql, (task['name'], task['description'], task['importance'], task['category'], task['deadline'], task_id))
    conn.commit()
    conn.close()
    sse.publish({"event": "PUT"}, type='update')
    return jsonify({'message': 'Task updated successfully'})

# Função para excluir uma tarefa no banco de dados
@app.route('/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    conn = create_connection()
    sql = 'DELETE FROM tasks WHERE id = ?'
    cur = conn.cursor()
    cur.execute(sql, (task_id,))
    conn.commit()
    conn.close()
    sse.publish({"event": "DELETE"}, type='delete')
    return jsonify({'message': 'Task deleted successfully'})

if __name__ == '__main__':
    create_table()
    app.run(debug=True)
