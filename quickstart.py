"""Do various discord and gsheet automation for the dominion league"""

import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError

import discord
import discord.ext.commands as commands # pylint: disable=consider-using-from-import
#import discord.ext
#from discord.ext import commands

from discord.bot import ApplicationCommandMixin


# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# The ID and range of a sample spreadsheet.
# SAMPLE_SPREADSHEET_ID = '1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms'
SAMPLE_SPREADSHEET_ID = "1O8-YTGYGBDFSjSReHLOmvGgBesrvMju8KEGqGWmxQpA"  # S53

TIMEOUT_TRIES = 10



USERS_NAME_HEADERS = ["username", "discriminator", "id"]
USERS_ROLE_HEADERS = [
    "Signup for League",
    "Late Signup for League",
    "New League Player",
    "League Player",
    "Current League Champion",
    "Former League Champion",
    "League Mod",
    "Proper League Division",
]


def get_requested_roles(sheet: Resource) -> dict[str, list[str]]:
    """returns a dict of discord_id's and requested discord roles given a season setup sheet"""
    result = None
    users: dict[str, list[str]] = {}
    for tries in range(TIMEOUT_TRIES):
        try:
            result = (
                sheet.values()
                .batchGet(
                    spreadsheetId=SAMPLE_SPREADSHEET_ID,
                    ranges=["Users!A2:C2", "Users!A3:C", "Users!O3:V"],
                )
                .execute()
            )
            break
        except TimeoutError as err:
            print(f"timeout #{tries} err: {err}")
            if tries == TIMEOUT_TRIES - 1:
                raise err
        except HttpError as err:
            print(f"httperror: {err}")
            if tries == TIMEOUT_TRIES - 1:
                raise err

    assert result is not None
    # result is a dict with spreadsheetId & valueRanges
    # valueRanges is a list of dicts
    # each dict has a key 'values', which is a 2D array
    value_ranges = result.get("valueRanges", [])

    if not value_ranges:
        print("No data found.")
        return {}

    name_headers, names, role_headers, requested_roles = [
        value_ranges[i]["values"] for i in range(len(value_ranges))
    ]

    assert name_headers == USERS_NAME_HEADERS
    assert role_headers == USERS_ROLE_HEADERS

    names = list(value_ranges[0]["values"])[:50]
    requested_roles = list(value_ranges[1]["values"])

    for name, roles in zip(names, requested_roles):
        users[name] = [
            role
            for role, requested in zip(role_headers, roles)
            if (requested == "TRUE")
        ]

    return users

class MyCog(commands.Cog):
    def __init__(self, bot, sheet_resource: Resource) -> None:
        super().__init__()
        self.bot = bot
        self.sheet_resource = sheet_resource

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'We have logged in as {self.bot.user}')

    @commands.command()
    async def hello(self, ctx, *, member: discord.Member = None):
        """Says hello"""
        member = member or ctx.author
        await ctx.send(f'Hello {member}~')




def main() -> None:
    """Shows basic usage of the Sheets API.
    Prints values from a sample spreadsheet.
    """
    creds = None

    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    service: Resource = build("sheets", "v4", credentials=creds)

    # Call the Sheets API
    sheet: Resource = service.spreadsheets()


    #intents = discord.Intents.default()
    #intents.members = True
    #bot = MyBot(intents=intents, sheet_resource = sheet)
    bot = commands.Bot()
    bot.add_cog(MyCog(bot, sheet))

    with open('discord_token', encoding='utf-8') as file:
        discord_token = file.readline().strip()
    bot.run(discord_token)


if __name__ == "__main__":
    main()
