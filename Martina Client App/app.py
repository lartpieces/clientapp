from datetime import datetime, timedelta
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
    
    # Financial Fields
    invoice = db.Column(db.Float, default=0.0)  # Amount paid by the client
    tips = db.Column(db.Float, default=0.0)     # Tips received
    martina_commission = db.Column(db.Float, default=0.0)  # 45% of Invoice

    # Automatically calculate Martina's commission before insert/update
    @staticmethod
    def calculate_commission(mapper, connection, target):
        target.martina_commission = round(target.invoice * 0.45, 2)

from sqlalchemy import event
event.listen(ClientVisit, 'before_insert', ClientVisit.calculate_commission)
event.listen(ClientVisit, 'before_update', ClientVisit.calculate_commission)


# Load data from Excel without duplicates
def import_excel_data():
    try:
        df = pd.read_excel("clients.xlsx").dropna(subset=["Client Name"])
        
        for _, row in df.iterrows():
            client_name = str(row["Client Name"]).strip()
            phone_number = str(row.get("Phone", "")).strip()
            visit_date = pd.to_datetime(row["Date"], errors="coerce")

            # Read financial values, default to 0 if missing
            invoice = float(row.get("Invoice", 0))  
            tips = float(row.get("Tips", 0))  

            if pd.isna(visit_date):
                continue

            existing_visit = ClientVisit.query.filter_by(name=client_name, visit_date=visit_date).first()
            if existing_visit:
                continue  # Skip duplicate visits

            new_client = ClientVisit(
                name=client_name,
                phone=phone_number,
                email="",
                visit_date=visit_date,
                next_followup=visit_date + timedelta(weeks=3),
                invoice=invoice,
                tips=tips
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

# Autocomplete Route
@app.route("/autocomplete")
def autocomplete():
    query = request.args.get("term", "").strip()
    if not query:
        return jsonify([])

    client_names = db.session.query(ClientVisit.name).filter(ClientVisit.name.ilike(f"%{query}%")).distinct().all()
    return jsonify([name[0] for name in client_names])

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
    invoice = float(request.form.get("invoice", 0))
    tips = float(request.form.get("tips", 0))

    if not name or not visit_date:
        return "Error: Client name and visit date are required", 400

    visit_date = datetime.strptime(visit_date, "%Y-%m-%d")

    existing_visit = ClientVisit.query.filter_by(name=name, visit_date=visit_date).first()
    if existing_visit:
        return "Error: Duplicate visit for the same day.", 400

    client = ClientVisit.query.filter_by(name=name).order_by(ClientVisit.visit_date.desc()).first()

    if client:
        client.next_followup = visit_date + timedelta(weeks=3)
        db.session.add(ClientVisit(name=client.name, phone=client.phone, email=client.email, visit_date=visit_date, next_followup=client.next_followup, invoice=invoice, tips=tips))
    else:
        return "Error: Client does not exist. Please add the client first.", 400

    db.session.commit()

    return redirect(url_for("home"))


# Filter Clients by Visit Date
@app.route("/filter_by_date")
def filter_by_date():
    try:
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()

        if not start_date or not end_date:
            return "Error: Both start and end dates are required", 400

        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)  # Include full end date

        clients = ClientVisit.query.filter(ClientVisit.visit_date.between(start_date, end_date)).all()

        return render_template("filtered_clients.html", clients=clients, start_date=start_date.date(), end_date=(end_date - timedelta(days=1)).date())

    except Exception as e:
        return f"Error: {e}", 500

# Inactive Clients    
@app.route("/inactive/<int:months>")
def inactive_clients(months):
    try:
        today = datetime.now()
        cutoff_date = today - timedelta(days=months * 30)

        # Debugging: Print cutoff date
        print(f"🔍 DEBUG: Cutoff Date for inactive clients: {cutoff_date}")

        # Query inactive clients (whose last visit was before cutoff_date)
        inactive_clients = db.session.query(
            ClientVisit.name,
            db.func.max(ClientVisit.visit_date).label("last_visit"),
            ClientVisit.phone
        ).group_by(ClientVisit.name, ClientVisit.phone) \
        .having(db.func.date(db.func.max(ClientVisit.visit_date)) < cutoff_date.date()) \
        .order_by(db.func.max(ClientVisit.visit_date).asc()).all()

        # Debugging: Print the number of inactive clients found
        print(f"🔍 DEBUG: Inactive Clients Found: {len(inactive_clients)}")

        return render_template("inactive_clients.html", clients=inactive_clients, months=months)

    except Exception as e:
        print(f"❌ Error retrieving inactive clients: {e}")
        return f"An error occurred: {e}", 500

@app.route("/last_visit_between")
def last_visit_between():
    try:
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()

        if not start_date or not end_date:
            return "Error: Both start and end dates are required.", 400

        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)  # Include full day

        # Find clients whose LAST visit was between the selected dates
        clients = db.session.query(
            ClientVisit.name,
            db.func.max(ClientVisit.visit_date).label("last_visit"),
            ClientVisit.phone
        ).group_by(ClientVisit.name, ClientVisit.phone) \
        .having(db.func.max(ClientVisit.visit_date).between(start_date, end_date)) \
        .order_by(db.func.max(ClientVisit.visit_date).desc()).all()

        return render_template("last_visit_between.html", clients=clients, start_date=start_date.date(), end_date=(end_date - timedelta(days=1)).date())

    except Exception as e:
        return f"Error retrieving last visit clients: {e}", 500

# Show visits for a client to delete
@app.route("/delete_visit", methods=["GET", "POST"])
def delete_visit():
    if request.method == "GET":
        name = request.args.get("name", "").strip()
        if not name:
            return "Error: Client name is required", 400

        # Fetch all visits for the given client name
        visits = db.session.query(
            ClientVisit.id,
            ClientVisit.visit_date
        ).filter(ClientVisit.name == name).order_by(ClientVisit.visit_date.desc()).all()

        return render_template("delete_visit.html", name=name, visits=visits)

    elif request.method == "POST":
        visit_id = request.form.get("visit_id")
        if not visit_id:
            return "Error: Visit ID is required", 400

        # Delete the selected visit
        visit = ClientVisit.query.get(visit_id)
        if visit:
            client_name = visit.name
            db.session.delete(visit)
            db.session.commit()

            # Find the latest remaining visit for this client
            latest_visit = db.session.query(ClientVisit).filter(ClientVisit.name == client_name).order_by(ClientVisit.visit_date.desc()).first()

            if latest_visit:
                # Update next follow-up based on the latest visit
                latest_visit.next_followup = latest_visit.visit_date + timedelta(weeks=3)
                db.session.commit()
            else:
                print(f"🔍 DEBUG: No remaining visits for {client_name}, setting follow-up to None.")

            return redirect(url_for("home"))
        else:
            return "Error: Visit not found", 404


@app.route("/income_report")
def income_report():
    try:
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()

        if not start_date or not end_date:
            return "Error: Both start and end dates are required", 400

        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)  # Include full end date

        clients = db.session.query(
            ClientVisit.name,
            ClientVisit.visit_date,
            ClientVisit.invoice,
            ClientVisit.tips,
            ClientVisit.martina_commission
        ).filter(ClientVisit.visit_date.between(start_date, end_date)).all()

        total_invoice = sum(client.invoice for client in clients)
        total_tips = sum(client.tips for client in clients)
        total_commission = sum(client.martina_commission for client in clients)

        return render_template("income_report.html", clients=clients, total_invoice=total_invoice, total_tips=total_tips, total_commission=total_commission)

    except Exception as e:
        return f"Error: {e}", 500


# Run the app
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        import_excel_data()
    app.run(debug=True)



