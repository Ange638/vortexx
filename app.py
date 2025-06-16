from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict
import json
import os
from flask_mail import Mail, Message
import fedapay
from fedapay import Transaction

fedapay.api_key = "sk_live_ZMlUwZAkko02M_LZjPr2UnzA"  # Remplace par ta clé secrète
fedapay.environment = "sandbox"  # "live" pour production


app = Flask(__name__)
# Configuration pour Gmail SMTP
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER')

mail = Mail(app)

app.secret_key = os.environ.get('SECRET_KEY', 'dev_key')


app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(25), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    points = db.Column(db.Integer, default=100)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def create_tables():
    db.create_all()

def load_data():
    if not os.path.exists('traite.json'):
        return []
    with open("traite.json", "r", encoding="utf-8") as f:
        return json.load(f)

parties = load_data()

stats_joueur = defaultdict(lambda: {"victoires": 0, "defaites": 0})
stats_banquier = defaultdict(lambda: {"victoires": 0, "defaites": 0})

for partie in parties:
    for main_j in partie["cartes_joueur"]:
        if partie["gagnant"] == "Joueur":
            stats_joueur[main_j.strip()]["victoires"] += 1
        elif partie["gagnant"] == "Banquier":
            stats_joueur[main_j.strip()]["defaites"] += 1

    for main_b in partie["cartes_banquier"]:
        if partie["gagnant"] == "Banquier":
            stats_banquier[main_b.strip()]["victoires"] += 1
        elif partie["gagnant"] == "Joueur":
            stats_banquier[main_b.strip()]["defaites"] += 1

def analyser_mains(main_j, main_b):
    res = {}
    stats_j = stats_joueur.get(main_j)
    stats_b = stats_banquier.get(main_b)

    if not stats_j:
        res['joueur'] = None
    else:
        vic = stats_j['victoires']
        defa = stats_j['defaites']
        total = vic + defa
        res['joueur'] = {
            "victoires": vic,
            "defaites": defa,
            "prob_victoire": vic / total if total > 0 else 0
        }

    if not stats_b:
        res['banquier'] = None
    else:
        vic = stats_b['victoires']
        defa = stats_b['defaites']
        total = vic + defa
        res['banquier'] = {
            "victoires": vic,
            "defaites": defa,
            "prob_victoire": vic / total if total > 0 else 0
        }

    if res['joueur'] and res['banquier']:
        p_j = res['joueur']['prob_victoire']
        p_b = res['banquier']['prob_victoire']
        if p_j > p_b:
            res['conclusion'] = f"Main Joueur favorise victoire du Joueur ({p_j:.2f} > {p_b:.2f})"
        elif p_b > p_j:
            res['conclusion'] = f"Main Banquier favorise victoire du Banquier ({p_b:.2f} > {p_j:.2f})"
        else:
            res['conclusion'] = "Probabilités égales, résultat incertain"
    elif res['joueur']:
        res['conclusion'] = "Seule la main du Joueur a été rencontrée dans l'historique."
    elif res['banquier']:
        res['conclusion'] = "Seule la main du Banquier a été rencontrée dans l'historique."
    else:
        res['conclusion'] = "Aucune des mains n'a été rencontrée auparavant."

    return res

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/abonnement', methods=['GET', 'POST'])
def abonnement():
    if 'user_id' not in session:
        flash("Veuillez vous connecter", "warning")
        return redirect(url_for('login'))

    if request.method == 'POST':
        montant = int(request.form['montant'])
        username = session['username']

        # Crée une transaction FedaPay
        from fedapay import Transaction, Customer

        try:
            transaction = Transaction.create({
                'description': f"Abonnement VORTEXstars - {username}",
                'amount': montant,
                'currency': {'iso': 'XOF'},
                'callback_url': url_for('callback', _external=True),
                'customer': {
                    'firstname': username,
                    'email': User.query.get(session['user_id']).email
                }
            })

            return redirect(transaction['url'])
        except Exception as e:
            flash(f"Erreur: {str(e)}", "danger")

    return render_template("abonnement.html")


@app.route('/callback')
def callback():
    user = User.query.get(session['user_id'])

    # Logique simplifiée : on ajoute les points selon le montant payé
    # Tu peux aussi sécuriser avec la vérification FedaPay API (webhook recommandé en prod)
    montant = request.args.get('amount', type=int, default=0)

    if montant >= 1000:
        user.points += 100
    elif montant >= 500:
        user.points += 40
    elif montant >= 200:
        user.points += 10
    else:
        flash("Montant non reconnu", "warning")
        return redirect(url_for('dashboard'))

    db.session.commit()
    flash("Abonnement réussi, points ajoutés !", "success")
    return redirect(url_for('dashboard'))


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']

        if not username or not email or not password:
            flash("Tous les champs sont obligatoires", "danger")
            return redirect(url_for('signup'))

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash("Nom d’utilisateur ou email déjà utilisé", "warning")
            return redirect(url_for('signup'))

        hashed_password = generate_password_hash(password)
        user = User(username=username, email=email, password=hashed_password)
        db.session.add(user)
        db.session.commit()

        flash("Compte créé avec succès, connectez-vous !", "success")
        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash(f"Bienvenue {user.username} !", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Identifiants invalides", "danger")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Déconnecté", "info")
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)

@app.route('/analyse', methods=['GET', 'POST'])
@login_required
def analyse():
    result = None
    if request.method == 'POST':
        main_j = request.form['main_joueur'].strip()
        main_b = request.form['main_banquier'].strip()

        if current_user.points <= 0:
            flash("Plus assez de points pour analyser.", "danger")
            return redirect(url_for('dashboard'))

        result = analyser_mains(main_j, main_b)

        current_user.points -= 10
        if current_user.points < 0:
            current_user.points = 0
        db.session.commit()

    return render_template('analyse.html', user=current_user, result=result)

if __name__ == "__main__":
    @app.context_processor
    def inject_current_year():
        from datetime import datetime
        return dict(current_year=datetime.now().year)

    app.run(debug=True)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        nom = request.form['nom']
        email = request.form['email']
        message = request.form['message']

        contenu = f"Nom: {nom}\nEmail: {email}\n\nMessage:\n{message}"

        try:
            msg = Message("📬 Nouveau message VORTEXstars", recipients=["tonemaildestinataire@gmail.com"])
            msg.body = contenu
            mail.send(msg)
            flash("Message envoyé avec succès. Merci de nous avoir contactés !", "success")
        except Exception as e:
            flash("Erreur lors de l'envoi du message. Réessayez plus tard.", "danger")
            print("Erreur email :", e)

        return redirect(url_for('contact'))

    return render_template('contact.html')

@app.route('/cgu')
def cgu():
    return render_template('cgu.html')

@app.route('/politique')
def politique():
    return render_template('politique.html')

    
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

