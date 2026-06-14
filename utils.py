import os
import io
import smtplib
import pandas as pd
import tailer
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz

def mkdir(folderpath, printout=False):
    ''' Create directory at folderpath if not already existing

    folderpath - can be relative or absolute
    '''
    try:
        # create the directory
        os.makedirs(folderpath, exist_ok=True)
        if printout:
            print(f"Directory '{folderpath}' created successfully")
        return folderpath

    except Exception as e:
        # fail to create directory
        if printout:
            print(f"Error creating directory '{folderpath}': {e}")
        return None


def get_lastline(filepath):
    ''' Determine the last line / entry in a file

    Assume file ends in blank line (i.e. eof newline)
    
    Notes: use seek/tell approach bc f.readlines()[-1] time complexity depends on file size
    '''
    try:
        with open(filepath, 'rb') as f:
            f.seek(-2,2)        # seek 2 shy of EOF (= opt 2) to avoid EOF "\n"
            pos = f.tell()      # get file position at eof
            
            while pos > 0:
                # move cursor backwards
                pos -= 1
                f.seek(pos)

                # read one byte at a time
                if f.read(1) == b'\n':
                    return f.readline().decode('utf-8').strip().split(",")
            
            f.seek(0)
            return f.readline().decode('utf-8').strip().split(",")
        
    except FileNotFoundError:
        return -1

    
def get_last_chunk_df(interval, ticker, chunk_size, dirFilepath):
    '''Compile the last chunk_size entries without reading entire savefile'''
    savefile_path = f"{dirFilepath}/Historical/{interval}_history/{ticker}.csv"

    with open(savefile_path) as f:
        header_line = f.readline().strip()
        # TODO: pick more pythonic method than tailer, io
        chunk = tailer.tail(f, chunk_size)

    # tailer returns the header row too if the file has fewer than chunk_size data rows
    if chunk and chunk[0] == header_line:
        chunk = chunk[1:]

    headers = header_line.split(",")[1:]
    if not chunk:
        return pd.DataFrame(columns=headers)

    chunk_df = pd.read_csv(io.StringIO('\n'.join(chunk)), index_col=0, header=None)
    # data rows may have fewer trailing columns than the header (e.g. yfinance
    # sometimes omits "Capital Gains"), so only assign the leading headers that
    # correspond to columns actually present
    chunk_df.columns = headers[:chunk_df.shape[1]]

    return chunk_df


def get_last_chunk(interval, ticker, chunk_size, dirFilepath):
    '''Compile the last chunk_size Close prices without reading entire savefile'''
    return get_last_chunk_df(interval, ticker, chunk_size, dirFilepath)["Close"].tolist()
    

def seconds_until_market_open(market, tz=pytz.timezone("America/New_York"), wait_less=0.99):
    # get trading schedule today
    now_dt = datetime.now(tz)
    start_day = now_dt.date()
    end_day = now_dt.date()
    schedule = market.schedule(start_day, end_day)

    # expand list if currently after trading hours or none exist today
    while schedule.empty or now_dt > schedule["market_close"].iloc[-1]:
        start_day += timedelta(days=1)
        end_day += timedelta(days=1)
        schedule = market.schedule(start_day, end_day)
    

    return round(max(0, wait_less*(schedule["market_open"].iloc[0] - now_dt).total_seconds()))
        

class SMS_Server:
    carrier_dict = {
        "ATT":"txt.att.net",
        "Boost":"myboostmobile.com",
        "Verizon":"vtext.com",
        "TMobile":"tmomail.net"
    }

    def __init__(self, smtp_server, port, dirFilepath):
        self.smtp_server = smtp_server
        self.port = port
        self.dirFilepath = dirFilepath

        load_dotenv(f"{dirFilepath}/.env")
        self.sender_addr = os.environ["GMAIL_ADDR"]
        self.sender_pwd = os.environ["GMAIL_APP_PASSWORD"]

        df = pd.read_csv(f"{dirFilepath}/SMS_Manager/contacts.csv", index_col=0)
        self.contact_names = df.index
        self.contact_numbers = df["Number"].astype(str)
        self.contact_carriers = df["Carrier"].astype(str)

    def sendSMS(self, phone_number, carrier, message):
        try:
            recipient_addr = phone_number + "@" + self.carrier_dict[carrier]
            
            self.server = smtplib.SMTP(self.smtp_server, self.port)
            self.server.starttls()
            self.server.ehlo()
            self.server.login(self.sender_addr, self.sender_pwd)

            self.server.sendmail(self.sender_addr, recipient_addr, message)
        
        except Exception as e:
            print(e)

        finally:
            self.server.quit()
    
    def send_distro(self, msg):
        for name in self.contact_names:
            number = self.contact_numbers.loc[name]
            carrier = self.contact_carriers.loc[name]
            self.sendSMS(number, carrier, msg)