from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from datetime import datetime, timedelta
import pandas as pd

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///clients.db'
db = SQLAlchemy(app)

# Database Model
class ClientVisit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    visit_date = db.Column(db.DateTime, default=datetime.utcnow)
    next_followup = db.Column(db.DateTime, nullable=True)

# Load data from Excel without duplicates
def import_excel_data():
    try:
        df = pd.read_excel("clients.xlsx").dropna(subset=["Client Name"])
        for _, row in df.iterrows():
            client_name = str(row["Client Name"]).strip()
            phone_number = str(row.get("Phone", "")).strip()
            visit_date = pd.to_datetime(row["Date"], errors="coerce")
            if pd.isna(visit_date):
                continue

            existing_visit = ClientVisit.query.filter_by(name=client_name, visit_date=visit_date).first()
            if existing_visit:
                continue  # Skip duplicate visits
            new_client = ClientVisit(
                name=client_name, phone=phone_number, email="", visit_date=visit_date, next_followup=visit_date + timedelta(weeks=3)
            )
            db.session.add(new_client)

        db.session.commit()
    except Exception as e:
        print("Error importing Excel data:", e)

# Home Page
@app.route("/")
def home():
    search_query = request.args.get("search", "").strip()
    clients = []

    if search_query:
        clients = db.session.query(
            ClientVisit.name,
            db.func.count(ClientVisit.id).label("visit_count"),
            db.func.max(ClientVisit.visit_date).label("last_visit"),
            ClientVisit.phone
        ).filter(ClientVisit.name.ilike(f"%{search_query}%")).group_by(ClientVisit.name).all()

    return render_template("index.html", clients=clients, search_query=search_query)

# Autocomplete Route (Ensuring Unique Names)
@app.route("/autocomplete")
def autocomplete():
    query = request.args.get("term", "").strip()
    if not query:
        return jsonify([])

    client_names = db.session.query(ClientVisit.name).filter(ClientVisit.name.ilike(f"%{query}%")).all()
    
    # Remove duplicates using a set and return as JSON
    unique_names = sorted(set(name[0] for name in client_names))  # Sorted for better UX
    return jsonify(unique_names)

# Show Clients to be Reminded in Next 7 Days
@app.route("/followups")
def followups():
    today = datetime.now()
    next_week = today + timedelta(days=7)
    clients_to_call = ClientVisit.query.filter(ClientVisit.next_followup != None, ClientVisit.next_followup.between(today, next_week)).all()
    return render_template("followups.html", clients=clients_to_call)

# Show Top 10 Loyal Clients
@app.route("/loyal_clients")
def loyal_clients():
    loyal_clients = db.session.query(
        ClientVisit.name,
        db.func.count(ClientVisit.id).label("visit_count")
    ).group_by(ClientVisit.name).order_by(db.desc("visit_count")).limit(10).all()
    
    return render_template("loyal_clients.html", clients=loyal_clients)

# View All Clients
@app.route("/clients_list")
def clients_list():
    clients = db.session.query(
        ClientVisit.name,
        db.func.count(ClientVisit.id).label("visit_count"),
        db.func.max(ClientVisit.visit_date).label("last_visit"),
        ClientVisit.phone
    ).group_by(ClientVisit.name).all()

    return render_template("clients_list.html", clients=clients)

# Add New Client
@app.route("/add_client", methods=["GET", "POST"])
def add_client():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        if not name:
            return "Error: Client name is required", 400
        
        visit_date = datetime.now()
        next_followup = visit_date + timedelta(weeks=3)
        new_client = ClientVisit(name=name, phone=phone, email=email, visit_date=visit_date, next_followup=next_followup)
        db.session.add(new_client)
        db.session.commit()
        return redirect(url_for("home"))
    return render_template("add_client.html")

# Add New Visit
@app.route("/add_visit", methods=["POST"])
def add_visit():
    name = request.form.get("name", "").strip()
    visit_date = request.form.get("visit_date", "").strip()
    if not name or not visit_date:
        return "Error: Client name and visit date are required", 400
    
    visit_date = datetime.strptime(visit_date, "%Y-%m-%d")

    # Ensure no duplicate visits on the same day
    existing_visit = ClientVisit.query.filter_by(name=name, visit_date=visit_date).first()
    if existing_visit:
        return "Error: Duplicate visit for the same day.", 400
    
    client = ClientVisit.query.filter_by(name=name).first()
    if client:
        new_visit = ClientVisit(
            name=client.name,
            phone=client.phone,
            email=client.email,
            visit_date=visit_date,
            next_followup=visit_date + timedelta(weeks=3)
        )
        db.session.add(new_visit)
    else:
        return "Error: Client does not exist. Please add the client first.", 400
    
    db.session.commit()
    return redirect(url_for("home"))

# Show clients who haven't visited in the last X months
@app.route("/inactive/<int:months>")
def inactive_clients(months):
    try:
        today = datetime.now()
        start_date = today - timedelta(days=months * 30)  # Start of the inactive period (e.g., Feb 7)
        end_date = today  # Today

        # Get clients whose **last visit was between start_date and today**
        inactive_clients = db.session.query(
            ClientVisit.name,
            db.func.max(ClientVisit.visit_date).label("last_visit"),
            ClientVisit.phone
        ).group_by(ClientVisit.name, ClientVisit.phone) \
        .having(db.func.max(ClientVisit.visit_date).between(start_date, end_date)) \
        .order_by(db.func.max(ClientVisit.visit_date).asc()).all()

        return render_template("inactive_clients.html", clients=inactive_clients, months=months)

    except Exception as e:
        print(f"Error retrieving inactive clients: {e}")
        return "An error occurred while retrieving inactive clients.", 500

# Run the app
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        import_excel_data()
    app.run(debug=True)
