# Chess-Bot By Scott Serven
This was initially based on [Chess-Bot By DaviOk](https://github.com/Davi0k/Chess-Bot), but has 
been mostly rewritten to support additional features, such as:

* Postgres match persistence in case of bot/server restarts
* Discord Slash commands
* Command optimizations
* UI upgrades
* Leaderboard

It makes use of the [python-chess](https://python-chess.readthedocs.io/en/latest/) library as a chess engine.

## Commands available within Chess-Bot
* `/new [user]`: Sends an invite for a new match to a specified `user`, or omit the `user` to open the match for anybody to accept.
* `/accept`: Accepts an invitation in the current channel, that is either open to anybody, or specifically sent to you.
* `/decline`: Decline an invitation that was specifically sent to you in the current channel.
* `/cancel`: Cancel an existing invitation you initiated with the `/new` command.
* `/move [start] [end]`: Takes a `start` and a `end` chess coordinate and executes a move in the current match.  These are in the format of A1 to H8.
* `/show`: Re-shows the current board.
* `/surrender`: Surrender and lose the current match.
* `/stats [user]`: Shows the statistics of wins/losses and ratio for either youself, or an optional specified user.
* `/leaderboard`: Shows the top 10 players according to the highest win/loss ratios.

## Some screen-shots about the BOT
![](https://i.ibb.co/BVcMNDj/Help.png)

![](https://i.ibb.co/hgks3Vp/Commands.png)

![](https://i.ibb.co/vv6RKHY/Start.png)


# Installation 

## Setup the Code

### Step 1 - Clone the source
Clone this repo somewhere.  I'd recommend using /opt and setting up a separate user to own the files.

### Step 2 - Setup a Virtual Environment

As the user that owns the source folder, run
```
python3 -m venv venv
source ./venv/bin/activate
pip install -r requirements.txt
```

### Step 3 - Setup a .env file

The `.env` file will hold important settings for the bot, and must be located in the root of the source folder.  The `.env.example` file will show the necessary values that must be setup.

`TOKEN` - this is the Discord Bot token you will get from the (Discord Bot Registration)[#Discord Bot Registration] section of these instructions.
`GUILD_IDS` - this may be one, or multiple (comma separate) Discord Server ID's that the bot will run against.
`STORAGE_TYPE` - this should be set to postgres, no other databases are currently supported.
`DATABASE_URL'` - this is a postgres formatted connection string. See the .env.example for the basic structure.


## Discord Bot Registration

### Step 1 - Create Discord App
1) Go to https://discord.com/developers/applications and create a new Application.

* All **General Information** fields can be left as their default values.

### Step 2 - Bot Setup
1) Go to the **Bot** menu and click **Add Bot**, and give it a name

2) Click **Reset Token**.  This will show your **Bot Token**.  This will need to be stored in your .env file in the TOKEN value.

3) Under **Privileged Gateway Intents**, enable:
    * Presence Intent
    * Server Members Intent
    * Message Content Intent

### Step 3 - Grant Bot Permissions
1) Click the **OAuth2** menu at the left, then **URL Generator**.
2) Under **Scopes**, select
    * **bot**
    * **applications.commands**

3) Under **Bot Permissions**, select
    * **Send Messages**
    * **Manage Messages**
    * **Attach Files**

4) Copy the **Generated URL** at the bottom of the page, and paste that into your browser address bar.
5) Choose which Discord server you want to grant the bot those permissions on.

## Setup Postgres

### Step 1 - Install Postgres
```bash
sudo apt install postgres 
```

### Step 2 - Create the Database/User

Launch the Postgres CLI interface (psql) as the postgres user (which was created automatically when postgres was installed during the prior step)

```bash
sudo -u postgres psql
```

Create a DB account for the bot (change 'chessbot-pwd' to whatever you want.  This value will be part
of the DATABASE_URL connection string in the `.env` file.

```sql
create user chessbot with password 'chessbot-pwd';
```

Create the database for the bot

```sql
create database chessbot with owner=chessbot;
```

Exit Postgres

```sql
quit
```
<br/>

## Run the Bot 
If everything has been setup correctly, you should be able to run the bot like
```bash
python bot.py
```

## Setup a Systemd Service (Optional)
If you're using a Systemd based system, you can create a `/etc/systemd/system/chessbot.service` file that looks like the following.

```bash
[Unit]
Description=ChessBot

[Service]
User=chessbot
WorkingDirectory=/opt/Chess-Bot/
ExecStart=/opt/Chess-Bot/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```
Make note to change the `User` value to whatever user account owns the Chess-Bot source folder.

The service can be enabled/started by running the following
```bash
sudo systemctl daemon-reload
sudo systemctl enable chessbot.service
sudo systemctl start chessbot.service
```

## License
This project is released under the `MIT License`. You can find the original license source here: [https://opensource.org/licenses/MIT](https://opensource.org/licenses/MIT).

```
MIT License

Copyright (c) 2020 Davide Casale
Copyright (c) 2023 Scott Serven

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```