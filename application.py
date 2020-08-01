import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # Retrieve portfolio for user from database
    user_portfolio = db.execute("SELECT price,sum(amount) as amount,symbol,s_name,cash "
                                "FROM portfolio "
                                "JOIN users ON portfolio.userId = users.id "
                                "JOIN stocks ON stocks.id = portfolio.symbolId "
                                "WHERE users.id = :id "
                                "GROUP BY symbolId",
                                id=session["user_id"])

    total = 0.0
    user_portfolio = list(filter(lambda x: x["amount"] != 0, user_portfolio))

    for entry in user_portfolio:
        entry["price"] = lookup(entry["symbol"])["price"]
        total += entry["amount"] * entry["price"]

    cash = db.execute("SELECT cash FROM users WHERE id= :id", id=session['user_id'])[0]['cash']
    total += cash

    return render_template("index.html", entrys=user_portfolio, cash=cash, total=total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    if request.method == 'POST':
        # Validate inputs
        symbol = request.form.get('symbol')
        amount = request.form.get('shares')

        if not symbol:
            return apology('missing symbol')
        if not amount:
            return apology('missing shares')

        # Try to lookup the symbol
        result = lookup(symbol)
        if not result:
            return apology('invalid symbol')

        # Check the input for shares
        try:
            amount = int(amount)
        except ValueError:
            return apology('invalid shares')

        if amount < 1:
            return apology('invalid shares')

        # Check if user can afford the shares
        total_cost = float(result['price']) * amount
        user_credit = db.execute("SELECT cash FROM users WHERE id = :id", id=session["user_id"])

        if total_cost > user_credit[0]["cash"]:
            return apology("can't afford")

        # Buy the shares
        # Insert stock symbol and name in stock table, if it doesn't already exist
        db.execute("INSERT OR IGNORE INTO stocks (symbol, s_name) VALUES (:symbol, :s_name)",
                   symbol=result['symbol'], s_name=result["name"])

        symbol_id = db.execute("SELECT id FROM stocks WHERE symbol = :symbol", symbol=result['symbol'])
        print(type(symbol_id))

        # Insert transaction in portfolio
        db.execute("INSERT INTO portfolio (userId,price,amount,symbolId) VALUES (:userId,:price,:amount,:symbolId)",
                   userId=session["user_id"], price=result["price"], amount=amount, symbolId=symbol_id[0]['id'])

        # Update user cash
        db.execute("UPDATE users SET cash = :updated WHERE id = :id ", updated=user_credit[0]["cash"] - total_cost,
                   id=session["user_id"])

        return redirect("/")

    return render_template("buy.html")


@app.route("/check", methods=["GET"])
def check():
    username = request.args.get("username")
    hits = db.execute("SELECT id "
                      "FROM users "
                      "WHERE username = :username", username=username)

    return jsonify((not hits) and (len(username) > 1))


@app.route("/history")
@login_required
def history():
    user_history = db.execute("SELECT price,amount,symbol,timestamp "
                              "FROM portfolio "
                              "JOIN users ON portfolio.userId = users.id "
                              "JOIN stocks ON stocks.id = portfolio.symbolId "
                              "WHERE users.id = :id ",
                              id=session["user_id"])

    return render_template("history.html", history=user_history)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 400)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    if request.method == "POST":

        # Get symbol
        symbol = request.form.get("symbol")

        # Check if symbol is set
        if not symbol:
            return apology("must provide a symbol", 400)

        # Lookup result for the symbol
        result = lookup(symbol)

        # Ensure that the lookup was successfull
        if not result:
            return apology("invalid symbol", 400)

        # Convert price to usd
        result['price'] = usd(result['price'])

        return render_template("quoted.html", result=result)

    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Store username and password for further processing
        username = request.form.get("username")
        password = request.form.get("password")
        password_rep = request.form.get("confirmation")

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=username)

        # Ensure username doesn't already exist
        if len(rows) >= 1:
            return apology("username is already taken", 400)
        else:
            if password != password_rep:
                return apology("passwords do not match", 400)

        # Generate password hash
        pw_hash = generate_password_hash(password)

        # Insert new user into database
        db.execute("INSERT INTO users (id,username,hash) VALUES (NULL,:username,:pw_hash)", username=username,
                   pw_hash=pw_hash)

        current_user = db.execute("SELECT * FROM users WHERE username = :username", username=username)

        # Log user in and remember which user has logged in
        session["user_id"] = current_user[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    if request.method == "POST":
        # handle sale and redirect to index page
        # validate inputs
        if request.form.get("symbol") == "":
            return apology("missing symbol")

        if not request.form.get("shares"):
            return apology("missing shares")

        selected_symbol = request.form.get("symbol")

        amount_of_shares_owned = db.execute("SELECT sum(amount) as amount "
                                            "FROM portfolio "
                                            "JOIN users ON portfolio.userId = users.id "
                                            "JOIN stocks ON stocks.id = portfolio.symbolId "
                                            "WHERE users.id = :id AND symbol = :symbol "
                                            "GROUP BY symbolId",
                                            id=session["user_id"], symbol=selected_symbol)[0]['amount']

        amount = request.form.get("shares")

        # try to cast amount to int to check if its a valid integer
        try:
            amount = int(amount)
        except ValueError:
            return apology('invalid shares')

        if amount < 1:
            return apology('invalid shares')

        if int(amount_of_shares_owned) < amount:
            return apology("Too many shares")

        symbol_id = db.execute("SELECT id FROM stocks WHERE symbol = :symbol", symbol=selected_symbol)[0]['id']
        current_stock_value = lookup(selected_symbol)['price']

        db.execute("INSERT INTO portfolio (userId,price,amount,symbolId) VALUES (:userId,:price,:amount,:symbolId)",
                   userId=session["user_id"], price=current_stock_value,
                   amount=-amount, symbolId=symbol_id)

        # add profit to user account
        current_value = float(current_stock_value) * float(amount_of_shares_owned)
        db.execute("UPDATE users SET cash = cash + :current_value WHERE id = :user_id", current_value=current_value,
                   user_id=session["user_id"])

        return redirect("/")

    else:
        # show template to sell shares
        user_id = session["user_id"]

        symbols = db.execute("SELECT symbol FROM portfolio "
                             "JOIN users ON portfolio.userId = users.id "
                             "JOIN stocks ON stocks.id = portfolio.symbolId "
                             "WHERE users.id = :id "
                             "GROUP BY symbol "
                             "HAVING SUM(amount) > 0", id=user_id)

        return render_template("sell.html", symbols=symbols)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
