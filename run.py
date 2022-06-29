from flask import Flask, request, session, render_template
from flask_session import Session
import mysql.connector
import json
import os
import re
import secrets
import hashlib
import string

# Open database connection
dblogininfofile = open("dbinfo.json", "r")
dblogininfo = json.load(dblogininfofile)
dblogininfofile.close()
dbconnection = mysql.connector.connect(
    host = dblogininfo['host'],
    username = dblogininfo['user'],
    password = dblogininfo['password'],
    db = dblogininfo['database']
)
dbconnection.autocommit = True
cursor = dbconnection.cursor(buffered=True)
app = Flask(__name__)
app.secret_key = dblogininfo['database']
dblogininfo = {}
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

# Create a users table if no users table exists
cursor.execute(
    "CREATE TABLE IF NOT EXISTS users ("
    "    userId INT AUTO_INCREMENT,"
    "    email VARCHAR(255) NOT NULL UNIQUE,"
    "    passkey VARCHAR(255) NOT NULL,"
    "    passsalt VARCHAR(255) NOT NULL,"
    "    PRIMARY KEY (userId)"
    ");"
)

# Author:
# ankthon
# https://www.geeksforgeeks.org/check-if-email-address-valid-or-not-in-python/
def validate_email(email):
    return re.fullmatch(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', email)

def generate_salt():
    alphabet = string.ascii_letters + string.digits
    salt = ''.join(secrets.choice(alphabet) for i in range(25))
    return salt

def is_logged_in():
    return session.get("userId") is not None

def get_user_id_from_email(email):
    cursor.execute(
        "SELECT userId FROM users WHERE email = %s;", [email]
    )
    result = cursor.fetchone()
    if result is None:
        return None
    return result[0]

def get_email_from_user_id(user_id):
    cursor.execute(
        "SELECT email FROM users WHERE userId = " + str(user_id) + ";"
    )
    result = cursor.fetchone()
    if result is None:
        return None
    return result[0]

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/get_open_conversations', methods = ['GET'])
def get_open_conversations():
    if not is_logged_in():
        return "\"not logged in\""
    userId = session.get("userId")
    cursor.execute(
        "SELECT DISTINCT userid_from FROM messages_" + str(userId) + " UNION "
        "SELECT DISTINCT userid_to FROM messages_" + str(userId) + ";"
    )
    open_ids = []
    for row in cursor.fetchall():
        if row[0] != userId:
            open_ids.append(get_email_from_user_id(row[0]))
    return json.dumps(open_ids)

@app.route('/send_message', methods = ['POST'])
def send_message():
    if not is_logged_in():
        return "\"not logged in\""

    emailTo = request.form.get("emailTo")
    content = request.form.get("content")
    if emailTo is None or content is None or emailTo == session["email"]:
        return "\"error\""
    
    userIdTo = get_user_id_from_email(emailTo)
    if userIdTo is None:
        return "\"user not found\""
    
    userIdFrom = session.get("userId")

    # Insert the message into both user message tables
    cursor.execute(
        "INSERT INTO messages_" + str(userIdFrom) + "  (userid_from, userid_to, content) VALUES ("
        "    " + str(userIdFrom) + ","
        "    " + str(userIdTo) + ","
        "    %s"
        ");", [content]
    )
    cursor.execute(
        "INSERT INTO messages_" + str(userIdTo) + "  (userid_from, userid_to, content) VALUES ("
        "    " + str(userIdFrom) + ","
        "    " + str(userIdTo) + ","
        "    (%s)"
        ");", [content]
    )
    return "\"message sent\""

@app.route('/get_messages', methods = ['POST'])
def get_messages():
    if not is_logged_in():
        return "\"not logged in\""

    emailPartner = request.form.get("emailPartner")

    if emailPartner is None or emailPartner == session["email"]:
        return "\"error\""

    partnerId = get_user_id_from_email(emailPartner)
    if partnerId is None:
        return "\"user not found\""

    myUserId = session.get("userId")

    cursor.execute(
        "SELECT * FROM messages_" + str(myUserId) + "  WHERE "
        "    userid_to = " + str(partnerId) + " OR "
        "    userid_from = " + str(partnerId) + " ORDER BY "
        "    date ASC"
        ";"
    )

    result = []
    for raw_row in cursor.fetchall():
        processed_row = []
        processed_row.append(get_email_from_user_id(raw_row[0]))
        processed_row.append(get_email_from_user_id(raw_row[1]))
        processed_row.append(raw_row[2])
        processed_row.append(raw_row[3])
        processed_row.append(raw_row[4])
        result.append(processed_row)
    return json.dumps(result, default=str)

@app.route('/register', methods = ['POST'])
def register():
    email = request.form.get("email")
    password = request.form.get("password")
    if email is not None and password is not None:
        if validate_email(email):
            cursor.execute(
                "SELECT COUNT(email) AS count FROM users WHERE email = '" + email + "';"
            )
            if cursor.fetchone()[0] == 0:
                # User does not exist
                salt = generate_salt()
                password_key = hashlib.pbkdf2_hmac(
                    'sha256',
                    password.encode(),
                    salt.encode(),
                    200000
                )

                # add user to users table
                cursor.execute(
                    "INSERT INTO users (email, passkey, passsalt) VALUES ("
                    "    '" + email + "',"
                    "    '" + password_key.hex() + "',"
                    "    '" + salt + "'"
                    ");"
                )

                # get user id
                cursor.execute(
                    "SELECT userId FROM users where email = '" + email + "';"
                )
                result = cursor.fetchone()
                if result is None:
                    return "Unknown error"

                userId = str(result[0])

                cursor.execute(
                    "CREATE TABLE messages_" + userId + " ("
                    "    userid_from INT NOT NULL,"
                    "    userid_to INT NOT NULL,"
                    "    content VARCHAR(10000) NOT NULL,"
                    "    date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                    "    messageId INT AUTO_INCREMENT,"
                    "    PRIMARY KEY (messageId)"
                    ");"
                )
                
                return "\"registration successful\""
            else:
                return "\"already registered\""
        else:
            return "\"invalid email\""
    else:
        return "\"missing information\""

@app.route('/login', methods = ['POST'])
def login():
    email = request.form.get("email")
    password = request.form.get("password")
    if email is not None and password is not None:
        if validate_email(email):
            cursor.execute(
                "SELECT userId, email, passkey, passsalt FROM users where email = '" + email + "';"
            )
            result = cursor.fetchone()
            if result is not None:
                userId = result[0]
                email = result[1]
                attempted_password_key = result[2]
                passsalt = result[3]

                real_password_key = hashlib.pbkdf2_hmac(
                    'sha256',
                    password.encode(),
                    passsalt.encode(),
                    200000
                ).hex()

                if real_password_key == attempted_password_key:
                    session["email"] = email
                    session["userId"] = userId
                    return "\"login successful\""
                else:
                    return "\"wrong password\""
            else:
                return "\"user not registered\""
        else:
            return "\"invalid email\""
    else:
        return "\"missing information\""
