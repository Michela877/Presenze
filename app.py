from flask import Flask, render_template, request, redirect, url_for, session, flash, get_flashed_messages, jsonify
import mysql.connector
import re
import bcrypt
import os
import datetime
import time

app = Flask(__name__, template_folder='templates')

app.secret_key = 'il_tuo_segreto'



# Configurazione del database MySQL
db_config = {
    'host': os.getenv('MYSQL_HOST', '40.65.111.152'),
    'port': os.getenv('MYSQL_PORT', '3306'),
    'user': os.getenv('MYSQL_USER', 'user'),
    'password': os.getenv('MYSQL_PASSWORD', 'password_base'),
    'database': os.getenv('MYSQL_DATABASE', 'asset_management')
}

# Variabile globale per memorizzare l'orario di inizio pausa
pause_start_time = None

@app.route('/home')
def home():
    email = request.args.get('email')
    if email:
        session['loggedin'] = True
        session['email'] = email

    if 'loggedin' in session:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        cursor.execute('SELECT id, nome, cognome FROM dipendenti WHERE email = %s', (session['email'],))
        dipendente = cursor.fetchone()

        if dipendente:
            dipendente_id = dipendente['id']
            dipendente_nome = dipendente['nome']
            dipendente_cognome = dipendente['cognome']

            query = '''
                SELECT p.*, d.nome AS dipendente_nome, d.cognome AS dipendente_cognome,
                       DATE_FORMAT(p.orario1_entrata, '%H:%i') AS orario1_entrata,
                       DATE_FORMAT(p.orario1_uscita, '%H:%i') AS orario1_uscita,
                       DATE_FORMAT(p.orario2_entrata, '%H:%i') AS orario2_entrata,
                       DATE_FORMAT(p.orario2_uscita, '%H:%i') AS orario2_uscita,
                       TIME_FORMAT(SEC_TO_TIME(
                           TIMESTAMPDIFF(SECOND, p.orario1_entrata, p.orario1_uscita) - COALESCE(p.orario_pausa * 60, 0)
                       ), '%H:%i') AS totale_ore_mattina,
                       TIME_FORMAT(SEC_TO_TIME(
                           TIMESTAMPDIFF(SECOND, p.orario1_entrata, p.orario1_uscita) +
                           TIMESTAMPDIFF(SECOND, p.orario2_entrata, p.orario2_uscita) - COALESCE(p.orario_pausa * 60, 0)
                       ), '%H:%i') AS totale_ore_giorno,
                       TIME_FORMAT(p.totale_ore_straordinari, '%H:%i') AS totale_ore_straordinari,
                       TIME_FORMAT(p.orario_inizio_straordinario, '%H:%i') AS straordinario_inizio,
                       TIME_FORMAT(p.orario_fine_straordinario, '%H:%i') AS straordinario_fine
                FROM presenze p
                JOIN dipendenti d ON p.id = d.id
                WHERE d.id = %s
                ORDER BY p.data_presenza DESC
            '''

            cursor.execute(query, (dipendente_id,))
            presenze = cursor.fetchall()

            cursor.close()
            conn.close()

            data_presenza = datetime.datetime.now().strftime('%Y-%m-%d')
            orario_entrata = datetime.datetime.now().strftime('%H:%M')
            orario_uscita = datetime.datetime.now().strftime('%H:%M')

            return render_template('home.html', 
                                   email=session['email'], 
                                   data_presenza=data_presenza, 
                                   orario_entrata=orario_entrata, 
                                   orario_uscita=orario_uscita, 
                                   presenze=presenze,
                                   dipendente_nome=dipendente_nome,
                                   dipendente_cognome=dipendente_cognome)
    return redirect('http://192.168.178.162:13000/')

def log_event(message, level='info'):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        timestamp = int(time.time())
        full_message = f"{level.upper()}: {message}"
        cursor.execute('INSERT INTO logs (timestamp, log) VALUES (%s, %s)', (timestamp, full_message))
        conn.commit()
        cursor.close()
        conn.close()
    except mysql.connector.Error as err:
        print(f"Errore di connessione al database per il logging: {err}")


@app.route('/')
def index():
    if 'loggedin' in session:
        log_event('User is logged in, redirecting to home page.')
        return redirect('http://40.65.111.152:14000/home?email=' + session['email'])
    log_event('User not logged in, rendering login page.')
    return redirect('http://40.65.111.152:13000/')

@app.route('/register_redirect')
def register_redirect():
    if 'loggedin' in session:
        log_event('User is logged in, redirecting to register page.')
        return redirect('http://40.65.111.152:11000/register?email=' + session['email'])
    log_event('User not logged in, rendering login page.')
    return redirect('http://40.65.111.152:13000/')

@app.route('/info')
def info():
    if 'loggedin' in session:
        log_event('User is logged in, redirecting to info page.')
        return redirect('http://40.65.111.152:18000/info?email=' + session['email'])
    log_event('User not logged in, rendering login page.')
    return redirect('http://40.65.111.152:13000/')

@app.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('email', None)
    log_event('User is logout, rendering login page.')
    return redirect('http://40.65.111.152:13000/')  # Reindirizza alla pagina di login dell'app di login

    
@app.route('/calcola_ore_straordinarie', methods=['POST'])
def calcola_ore_straordinarie():
    if 'loggedin' in session:
        email = session['email']
        data_presenza = request.form.get('data_presenza')

        if not data_presenza:
            flash('Data presenza non fornita.', 'error')
            log_event('Data presenza non fornita.', 'error')
            return redirect(url_for('home'))

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT id FROM dipendenti WHERE email = %s', (email,))
            dipendente_id = cursor.fetchone()[0]
            
            aggiorna_ore_straordinarie(dipendente_id, data_presenza)
            flash('Ore straordinarie calcolate con successo.', 'success')

        except mysql.connector.Error as err:
            flash('Si è verificato un errore durante il calcolo delle ore straordinarie.', 'error')
            log_event('Si è verificato un errore durante il calcolo delle ore straordinarie.', 'error')
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('home'))
    return redirect('http://40.65.111.152:13000/')



    
def aggiorna_ore_straordinarie(dipendente_id, data_presenza):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    # Funzione per calcolare la differenza in secondi
    def calcola_differenza(start, end):
        start_dt = datetime.strptime(start, '%H:%M')
        end_dt = datetime.strptime(end, '%H:%M')
        return (end_dt - start_dt).total_seconds()

    # Query per calcolare le ore straordinarie basate su orario_inizio_straordinario e orario1_entrata
    query_orario1_entrata = '''
        UPDATE presenze p
        JOIN (
            SELECT
                p.id,
                SEC_TO_TIME(
                    GREATEST(
                        0,
                        TIMESTAMPDIFF(SECOND, p.orario_inizio_straordinario, p.orario1_entrata)
                    )
                ) AS ore_straordinarie_calcolate
            FROM presenze p
            WHERE p.id = %s AND p.data_presenza = %s
              AND p.orario_inizio_straordinario IS NOT NULL
              AND p.orario1_entrata IS NOT NULL
        ) calcolo ON p.id = calcolo.id
        SET p.totale_ore_straordinari = calcolo.ore_straordinarie_calcolate
        WHERE p.id = calcolo.id AND p.data_presenza = %s;
    '''

    # Query per calcolare le ore straordinarie basate su orario1_uscita e orario_fine_straordinario
    query_orario1_uscita = '''
        UPDATE presenze p
        JOIN (
            SELECT
                p.id,
                SEC_TO_TIME(
                    GREATEST(
                        0,
                        TIMESTAMPDIFF(SECOND, p.orario1_uscita, p.orario_fine_straordinario)
                    )
                ) AS ore_straordinarie_calcolate
            FROM presenze p
            WHERE p.id = %s AND p.data_presenza = %s
              AND p.orario1_uscita IS NOT NULL
              AND p.orario_fine_straordinario IS NOT NULL
        ) calcolo ON p.id = calcolo.id
        SET p.totale_ore_straordinari = SEC_TO_TIME(
            TIME_TO_SEC(IFNULL(p.totale_ore_straordinari, '00:00:00')) + TIME_TO_SEC(calcolo.ore_straordinarie_calcolate)
        )
        WHERE p.id = calcolo.id AND p.data_presenza = %s;
    '''
    

    # Esegui i calcoli in ordine
    cursor.execute(query_orario1_entrata, (dipendente_id, data_presenza, data_presenza))
    cursor.execute(query_orario1_uscita, (dipendente_id, data_presenza, data_presenza))

    
    conn.commit()
    cursor.close()
    conn.close()

@app.route('/aggiungi_entrata', methods=['POST'])
def aggiungi_entrata():
    if 'loggedin' in session:
        email = session['email']
        data_presenza = request.form['data_presenza']
        orario_entrata = request.form['orario_entrata']

        try:
            orario_entrata_dt = datetime.datetime.strptime(orario_entrata, '%H:%M').time()
            orario_attuale = datetime.datetime.now().time()
            
            if orario_entrata_dt < datetime.time(9, 0):
                orario1_entrata = '09:00'
                orario_inizio_straordinario = orario_attuale.strftime('%H:%M')
            else:
                orario1_entrata = orario_entrata
                orario_inizio_straordinario = None

            print(f"Orario entrata: {orario1_entrata}, Straordinario: {orario_inizio_straordinario}")  # Log per debug
            log_event(f"Orario entrata: {orario1_entrata}, Straordinario: {orario_inizio_straordinario}")

        except ValueError as e:
            print(f"Errore nel parsing dell'orario: {e}")  # Log per debug
            flash('Orario di entrata non valido.', 'error')
            log_event(f"Errore nel parsing dell'orario: {e}")
            return redirect(url_for('home'))

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT id FROM dipendenti WHERE email = %s', (email,))
            dipendente_id = cursor.fetchone()[0]
            
            cursor.execute('SELECT orario1_entrata, orario2_entrata, orario1_uscita FROM presenze WHERE id = %s AND data_presenza = %s', (dipendente_id, data_presenza))
            presenze = cursor.fetchone()

            if presenze:
                orario1_entrata_esistente, orario2_entrata, orario1_uscita = presenze
                if orario1_entrata_esistente is not None and orario2_entrata is not None:
                    flash('Entrambe le entrate per oggi sono già state inserite.', 'error')
                    log_event('Entrambe le entrate per oggi sono già state inserite.', 'error')
                elif orario1_entrata_esistente is not None and orario1_uscita is None:
                    flash('Devi registrare l\'uscita prima di poter inserire una seconda entrata.', 'error')
                    log_event('Devi registrare l\'uscita prima di poter inserire una seconda entrata.', 'error')
                elif orario1_entrata_esistente is not None:
                    cursor.execute('UPDATE presenze SET orario2_entrata = %s WHERE id = %s AND data_presenza = %s', (orario_entrata, dipendente_id, data_presenza))
                    flash('Secondo orario di entrata inserito con successo.', 'success')
                    log_event('Secondo orario di entrata inserito con successo.', 'success')
                else:
                    cursor.execute('UPDATE presenze SET orario1_entrata = %s, orario_inizio_straordinario = %s WHERE id = %s AND data_presenta = %s', 
                                   (orario1_entrata, orario_inizio_straordinario, dipendente_id, data_presenza))
                    flash('Primo orario di entrata inserito con successo.', 'success')
                    log_event('Primo orario di entrata inserito con successo.', 'success')
            else:
                cursor.execute('INSERT INTO presenze (id, data_presenza, orario1_entrata, orario_inizio_straordinario) VALUES (%s, %s, %s, %s)', 
                               (dipendente_id, data_presenza, orario1_entrata, orario_inizio_straordinario))
                flash('Primo orario di entrata inserito con successo.', 'success')
                log_event('Primo orario di entrata inserito con successo.', 'success')

            conn.commit()
            print("Operazione completata con successo")  # Log per debug
            log_event("Operazione completata con successo")

        except mysql.connector.Error as err:
            print(f"Errore del database: {err}")  # Log per debug
            log_event(f"Errore del database: {err}")
            conn.rollback()
            flash('Si è verificato un errore durante l\'inserimento dei dati.', 'error')
            log_event('Si è verificato un errore durante l\'inserimento dei dati.', 'error')

        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('home'))
    return redirect(url_for('login'))
    
@app.route('/aggiungi_uscita', methods=['POST'])
def aggiungi_uscita():
    if 'loggedin' in session:
        email = session['email']
        data_presenza = request.form['data_presenza']
        orario_uscita = request.form['orario_uscita']

        try:
            orario_uscita_dt = datetime.datetime.strptime(orario_uscita, '%H:%M').time()
            orario_attuale = datetime.datetime.now().time()

            # Imposta orario_fine_straordinario solo se l'orario di uscita supera le 18:00
            if orario_uscita_dt > datetime.time(18, 0):
                orario1_uscita = '18:00'  # Imposta orario1_uscita su 18:00 se oltre le 18:00
                orario_fine_straordinario = orario_uscita  # Imposta orario_fine_straordinario a orario_uscita
            else:
                orario1_uscita = orario_uscita  # Imposta orario1_uscita a orario_uscita se entro le 18:00
                orario_fine_straordinario = None  # Imposta orario_fine_straordinario a None se entro le 18:00

            print(f"Orario uscita: {orario1_uscita}, Straordinario: {orario_fine_straordinario}")  # Log per debug
            log_event(f"Orario uscita: {orario1_uscita}, Straordinario: {orario_fine_straordinario}")

        except ValueError as e:
            print(f"Errore nel parsing dell'orario: {e}")  # Log per debug
            flash('Orario di uscita non valido.', 'error')
            log_event(f"Errore nel parsing dell'orario: {e}")
            return redirect(url_for('home'))

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT id FROM dipendenti WHERE email = %s', (email,))
            dipendente_id = cursor.fetchone()[0]

            # Recupera gli orari di presenza esistenti
            cursor.execute('SELECT orario1_uscita, orario2_uscita, orario1_entrata, orario2_entrata FROM presenze WHERE id = %s AND data_presenza = %s', (dipendente_id, data_presenza))
            presenze = cursor.fetchone()

            if presenze:
                orario1_uscita_esistente, orario2_uscita_esistente, orario1_entrata, orario2_entrata = presenze

                # Controlla e aggiorna gli orari di uscita
                if orario1_uscita_esistente is not None and orario2_uscita_esistente is not None:
                    flash('Entrambe le uscite per oggi sono già state inserite.', 'error')
                    log_event('Entrambe le uscite per oggi sono già state inserite.', 'error')
                elif orario1_entrata is None:
                    flash('Devi registrare l\'entrata prima di poter inserire un\'uscita.', 'error')
                    log_event('Devi registrare l\'entrata prima di poter inserire un\'uscita.', 'error')
                elif orario1_uscita_esistente is not None and orario2_entrata is None:
                    flash('Devi registrare la seconda entrata prima di poter inserire una seconda uscita.', 'error')
                    log_event('Devi registrare la seconda entrata prima di poter inserire una seconda uscita.', 'error')
                elif orario1_uscita_esistente is not None:
                    if orario2_uscita_esistente is None:  # Solo se orario2_uscita è None
                        cursor.execute('UPDATE presenze SET orario2_uscita = %s WHERE id = %s AND data_presenza = %s',
                                       (orario_uscita, dipendente_id, data_presenza))
                        flash('Secondo orario di uscita inserito con successo.', 'success')
                        log_event('Secondo orario di uscita inserito con successo.', 'success')
                    else:
                        flash('Orario di uscita già registrato per il secondo turno.', 'error')
                        log_event('Orario di uscita già registrato per il secondo turno.', 'error')
                else:
                    cursor.execute('UPDATE presenze SET orario1_uscita = %s, orario_fine_straordinario = %s WHERE id = %s AND data_presenza = %s',
                                   (orario1_uscita, orario_fine_straordinario, dipendente_id, data_presenza))
                    flash('Primo orario di uscita inserito con successo.', 'success')
                    log_event('Primo orario di uscita inserito con successo.', 'success')
            else:
                flash('Devi registrare un\'entrata prima di poter inserire un\'uscita.', 'error')
                log_event('Devi registrare un\'entrata prima di poter inserire un\'uscita.', 'error')

            conn.commit()
            print("Operazione completata con successo")  # Log per debug
            log_event("Operazione completata con successo")

        except mysql.connector.Error as err:
            print(f"Errore del database: {err}")  # Log per debug
            log_event(f"Errore del database: {err}")
            conn.rollback()
            flash('Si è verificato un errore durante l\'inserimento dei dati.', 'error')
            log_event('Si è verificato un errore durante l\'inserimento dei dati.', 'error')

        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('home'))
    return redirect(url_for('login'))
    
@app.route('/toggle_pausa', methods=['POST'])
def toggle_pausa():
    global pause_start_time
    
    email = session.get('email')
    if not email:
        return jsonify({"status": "error", "message": "Utente non autenticato"}), 401

    today_date = datetime.date.today()
    
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        if pause_start_time is None:
            # Inizio pausa
            cursor.execute('''
                SELECT id_num, orario1_entrata, orario1_uscita
                FROM presenze
                WHERE id = (SELECT id FROM dipendenti WHERE email = %s) AND data_presenza = %s
                ORDER BY id_num DESC
                LIMIT 1
                ''', (email, today_date))
            presenze = cursor.fetchone()

            if presenze:
                id_num, orario1_entrata, orario1_uscita = presenze
                
                if orario1_entrata is None:
                    return jsonify({"status": "error", "message": "Devi registrare l'entrata del primo turno prima di iniziare la pausa"})
                
                if orario1_uscita is not None:
                    return jsonify({"status": "error", "message": "Non puoi iniziare la pausa dopo l'uscita del primo turno"})
                
                # Inizio pausa
                pause_start_time = datetime.datetime.now()
                return jsonify({"status": "paused", "start_time": pause_start_time.isoformat()})
            else:
                return jsonify({"status": "error", "message": "Nessuna registrazione di presenza trovata per oggi"})
        
        else:
            # Fine pausa
            password = request.form.get('password')
            if not password:
                return jsonify({"status": "error", "message": "Password richiesta per terminare la pausa"})
            
            cursor.execute('SELECT credenziali_accesso FROM login WHERE email = %s', (email,))
            result = cursor.fetchone()

            if result:
                stored_password = result[0]
                if bcrypt.checkpw(password.encode('utf-8'), stored_password.encode('utf-8')):
                    pausa_end_time = datetime.datetime.now()
                    pausa_duration = (pausa_end_time - pause_start_time).total_seconds() / 60

                    if pausa_duration < 1:
                        return jsonify({"status": "error", "message": "Non puoi fermare la pausa prima di 1 minuto. Attendi un minuto per fermare la pausa."})

                    pause_start_time = None

                    cursor.execute('''
                        UPDATE presenze
                        SET orario_pausa = COALESCE(orario_pausa, 0) + %s
                        WHERE id = (SELECT id FROM dipendenti WHERE email = %s) AND data_presenza = %s
                        ORDER BY id_num DESC
                        LIMIT 1
                        ''', (pausa_duration, email, today_date))
                    conn.commit()
                    
                    
                    return jsonify({"status": "resumed", "duration": pausa_duration})
                else:
                    return jsonify({"status": "error", "message": "Password non valida"})
            else:
                return jsonify({"status": "error", "message": "Email non trovata"})
    
    except mysql.connector.Error as err:
        return jsonify({"status": "error", "message": f"Database error: {err}"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"An error occurred: {e}"})
    finally:
        cursor.close()
        conn.close()

@app.route('/get_pause_time', methods=['GET'])
def get_pause_time():
    if pause_start_time:
        current_time = datetime.datetime.now()
        elapsed_time = (current_time - pause_start_time).total_seconds()
        return jsonify({"elapsed_time": elapsed_time})
    else:
        return jsonify({"elapsed_time": 0})
    
@app.route('/filtra_presenze', methods=['POST'])
def filtra_presenze():
    if 'loggedin' in session:
        email = session['email']
        data_inizio = request.form.get('data_inizio')
        data_fine = request.form.get('data_fine')

        if not data_inizio or not data_fine:
            flash('Data di inizio o di fine non fornita.', 'error')
            log_event('Data di inizio o di fine non fornita.', 'error')
            return redirect(url_for('home'))

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        try:
            # Ottieni l'ID del dipendente
            cursor.execute('SELECT id FROM dipendenti WHERE email = %s', (email,))
            result = cursor.fetchone()

            if not result:
                flash('Dipendente non trovato.', 'error')
                log_event('Dipendente non trovato.', 'error')
                return redirect(url_for('home'))

            dipendente_id = result['id']

            # Esegui la query per le presenze
            query = '''
                SELECT p.*, d.nome AS dipendente_nome, d.cognome AS dipendente_cognome,
                       DATE_FORMAT(p.orario1_entrata, '%H:%i') AS orario1_entrata,
                       DATE_FORMAT(p.orario1_uscita, '%H:%i') AS orario1_uscita,
                       DATE_FORMAT(p.orario2_entrata, '%H:%i') AS orario2_entrata,
                       DATE_FORMAT(p.orario2_uscita, '%H:%i') AS orario2_uscita,
                       TIME_FORMAT(SEC_TO_TIME(
                           TIMESTAMPDIFF(SECOND, p.orario1_entrata, p.orario1_uscita) - COALESCE(p.orario_pausa * 60, 0)
                       ), '%H:%i') AS totale_ore_mattina,
                       TIME_FORMAT(SEC_TO_TIME(
                           TIMESTAMPDIFF(SECOND, p.orario1_entrata, p.orario1_uscita) +
                           TIMESTAMPDIFF(SECOND, p.orario2_entrata, p.orario2_uscita) - COALESCE(p.orario_pausa * 60, 0)
                       ), '%H:%i') AS totale_ore_giorno,
                       TIME_FORMAT(p.totale_ore_straordinari, '%H:%i') AS totale_ore_straordinari,
                       TIME_FORMAT(p.orario_inizio_straordinario, '%H:%i') AS straordinario_inizio,
                       TIME_FORMAT(p.orario_fine_straordinario, '%H:%i') AS straordinario_fine
                FROM presenze p
                JOIN dipendenti d ON p.id = d.id
                WHERE d.id = %s AND p.data_presenza BETWEEN %s AND %s
                ORDER BY p.data_presenza DESC
            '''

            cursor.execute(query, (dipendente_id, data_inizio, data_fine))
            presenze = cursor.fetchall()

            # Ottieni dati di presenza attuali
            data_presenza = datetime.datetime.now().strftime('%Y-%m-%d')
            orario_entrata = datetime.datetime.now().strftime('%H:%M')
            orario_uscita = datetime.datetime.now().strftime('%H:%M')

            # Ottieni il nome e il cognome del dipendente
            cursor.execute('SELECT nome, cognome FROM dipendenti WHERE id = %s', (dipendente_id,))
            dipendente_data = cursor.fetchone()
            
            dipendente_nome = dipendente_data['nome'] if dipendente_data else 'Nome non trovato'
            dipendente_cognome = dipendente_data['cognome'] if dipendente_data else 'Cognome non trovato'

            return render_template('home.html', 
                                   email=session['email'], 
                                   data_presenza=data_presenza, 
                                   orario_entrata=orario_entrata, 
                                   orario_uscita=orario_uscita, 
                                   presenze=presenze,
                                   dipendente_nome=dipendente_nome,
                                   dipendente_cognome=dipendente_cognome)

        except mysql.connector.Error as err:
            flash(f'Si è verificato un errore durante il filtraggio delle presenze: {err}', 'error')
            log_event(f'Si è verificato un errore durante il filtraggio delle presenze: {err}', 'error')
            return redirect(url_for('home'))

        finally:
            cursor.close()
            conn.close()

    return redirect('http://40.65.111.152:13000/')

    


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=14000)
