"""Do various discord and gsheet automation for the dominion league"""

import os.path
import asyncio
import pickle
from typing import TypeAlias, cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError

import nextcord
import nextcord.ext.commands as commands  # pylint: disable=consider-using-from-import

# import nextcord.ext
# from nextcord.ext import commands


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

RoleList: TypeAlias = dict[int, list[str]]


async def get_requested_roles(sheet: Resource) -> RoleList:
    """returns a dict of discord_id's and requested discord roles given a season setup sheet"""
    print("poop")
    result = None
    users: RoleList = {}
    for tries in range(TIMEOUT_TRIES):
        try:
            result = (
                sheet.values()
                .batchGet(
                    spreadsheetId=SAMPLE_SPREADSHEET_ID,
                    ranges=["Users!A2:C2", "Users!O2:V2", "Users!A3:C", "Users!O3:V"],
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

    name_headers, role_headers, names, requested_roles = [
        value_ranges[i]["values"] for i in range(len(value_ranges))
    ]

    name_headers = name_headers.pop()
    role_headers = role_headers.pop()

    assert name_headers == USERS_NAME_HEADERS
    assert role_headers == USERS_ROLE_HEADERS

    for (_, _, d_id), roles in zip(names, requested_roles):
        req_roles = [
            role
            for role, requested in zip(role_headers, roles)
            if (requested == "TRUE")
        ]

        if not req_roles:
            continue
        users[int(d_id)] = req_roles

    return users


def get_roles(guild: nextcord.Guild, user_id: int) -> list[str]:
    """returns a list of roles for a given discord user"""
    roles: list[str] = []
    member = guild.get_member(user_id)
    if member is None:
        return roles
    for role in member.roles:
        roles.append(role.name)
    return roles


def mismatching_roles(
    guild: nextcord.Guild, requested_roles: RoleList
) -> dict[nextcord.Member, tuple[set[nextcord.Role], set[nextcord.Role]]]:
    def role_lookup(rolename: str) -> nextcord.Role:
        role = roles_lookup.pop(rolename, None)
        if role is not None:
            return role
        for role in guild.roles:
            if role.name == rolename:
                return role
        raise ValueError("role {rolename} not found")

    roles_lookup: dict[str, nextcord.Role] = {}
    result = {}

    for d_id, roles in requested_roles.items():
        member = guild.get_member(d_id)
        if member is None:
            # TODO
            print(f"failed to find member {d_id}")
            continue

        # TODO: division roles
        parsed_roles = set(role_lookup(role) for role in roles)
        actual_roles = set(member.roles)
        add_roles = parsed_roles - actual_roles
        remove_roles = {
            r for r in actual_roles - parsed_roles if r.name in USERS_ROLE_HEADERS
        }
        if not add_roles and not remove_roles:
            continue
        result[member] = (add_roles, remove_roles)

    print([(f"@{m.name}#{m.discriminator}", roles) for m, roles in result.items()])
    return result


class MyCog(commands.Cog):
    def __init__(self, bot, sheet_resource: Resource) -> None:
        super().__init__()
        self.bot = bot
        self.sheet_resource = sheet_resource
        self.background_tasks: set[asyncio.tasks.Task] = set()

    async def my_wrapper(self, channel: nextcord.abc.Messageable):
        req_roles = await get_requested_roles(self.sheet_resource)
        with open("req_roles.pickle", "wb") as file:
            pickle.dump(req_roles, file)
        await channel.send(f"updated {len(req_roles)} entries")

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"We have logged in as {self.bot.user}")

    @nextcord.slash_command(dm_permission=True)
    async def hello(
        self, interaction: nextcord.Interaction, *, member: nextcord.Member = None
    ):
        """Says hello"""
        hello_target = member or interaction.user
        if hello_target is None:
            await interaction.send("Hello :)")
            return
        await interaction.send(f"Hello <@{hello_target.id}>~")

    @nextcord.slash_command(dm_permission=True)
    async def addrole(
        self,
        interaction: nextcord.Interaction,
        *,
        member: nextcord.Member,
        role: nextcord.Role,
    ):
        """Add role to user"""
        if role in member.roles:
            await interaction.send(f"<@{member.id}> already has role `{role}`")
            return

        await member.add_roles(
            cast(nextcord.abc.Snowflake, role),
            reason=f"function: addrole, caller: {interaction.user}",
        )
        await interaction.send(f"Adding `{role}` to <@{member.id}>")

    @nextcord.slash_command(dm_permission=True)
    async def removerole(
        self,
        interaction: nextcord.Interaction,
        *,
        member: nextcord.Member,
        role: nextcord.Role,
    ):
        """Remove role from user"""
        if role not in member.roles:
            await interaction.send(f"<@{member.id}> does not have role `{role}`")
            return

        await member.remove_roles(
            cast(nextcord.abc.Snowflake, role),
            reason=f"function: removerole, caller: {interaction.user}",
        )
        await interaction.send(f"Removing `{role}` from <@{member.id}>")

    @nextcord.slash_command(dm_permission=True)
    async def update_requested_roles(self, interaction: nextcord.Interaction):
        """Update cache of requested roles in Setup sheet in the background"""
        task = asyncio.create_task(
            self.my_wrapper(cast(nextcord.abc.Messageable, interaction.channel))
        )
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        await interaction.send("Running sheets update in background...")

    @nextcord.slash_command(dm_permission=True)
    async def quit(self, interaction: nextcord.Interaction):
        """Quits"""
        print("quitting")
        await interaction.send("Quitting~")
        await self.bot.close()

    @nextcord.slash_command(dm_permission=True)
    async def mismatching_roles(self, interaction: nextcord.Interaction):
        """Print which league roles are missing/extranous according to setup sheet"""
        # warn if out of date, error if missing
        with open("req_roles.pickle", "rb") as file:
            requested_roles = pickle.load(file)
        dom_guild = [g for g in self.bot.guilds if g.id == 212660788786102272].pop()
        mmmr = mismatching_roles(dom_guild, requested_roles)
        # TODO: send members not found

        lines = []
        for member, (add, remove) in mmmr.items():
            strname = member.name + "#" + str(member.discriminator)
            linestring = f"{strname:25}"
            if add:
                linestring += "".join([f" +{r.name:10}" for r in add])
            if remove:
                linestring += "".join([f" -{r.name:10}" for r in remove])
            lines.append(linestring)

        await interaction.send("```" + "\n".join(lines) + "```")

    @nextcord.slash_command(dm_permission=True)
    async def fix_roles(self, interaction: nextcord.Interaction, *, write: bool = False):
        """Fix league roles according to setup sheet. POTENTIALLY DANGEROUS

        Parameters
        ---------
        write: Optional[bool]
            Set to True to actually make changes to roles. Will otherwise just print changes.
        """
        with open("req_roles.pickle", "rb") as file:
            requested_roles = pickle.load(file)
        dom_guild = [g for g in self.bot.guilds if g.id == 212660788786102272].pop()
        mmmr = mismatching_roles(dom_guild, requested_roles)
        if not write:
            response = ['Running in dummy mode, not changing any roles']
        else:
            response = []
        for member, (add, remove) in mmmr.items():
            if add:
                if write:
                    await member.add_roles(*add, reason=f'Added in fix_roles on behest of {interaction.user}')
                response.append(f'Added {[r.name for r in add]} to <@{member.id}>')

            if remove:
                if write:
                    await member.remove_roles(*remove, reason=f'Added in fix_roles on behest of {interaction.user}')
                response.append(f'Removed {[r.name for r in remove]} from <@{member.id}>')
        await interaction.send('\n'.join(response))


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
    sheet: Resource = service.spreadsheets()  # pylint: disable=no-member

    intents = nextcord.Intents.default()
    intents.members = True  # pylint: disable=assigning-non-slot
    # bot = MyBot(intents=intents, sheet_resource = sheet)
    bot = commands.Bot(intents=intents)
    bot.add_cog(MyCog(bot, sheet))

    with open("discord_token", encoding="utf-8") as file:
        discord_token = file.readline().strip()
    bot.run(discord_token)


if __name__ == "__main__":
    main()
