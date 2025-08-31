import os
import smtplib
import pandas as pd

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
                    break
            
            # f.read() advances cursor, so return current line as str. Strip spaces, including newline
            return f.readline().decode('utf-8').strip().split(",")
        
    except FileNotFoundError:
        return -1
    
    except Exception as e:
        return 0
    

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

        df = pd.read_csv(f"{dirFilepath}/SMS_Manager/sender_details.csv", index_col=0)
        self.sender_addr = df.at["sender_addr","Value"]
        self.sender_pwd = df.at["sender_pwd","Value"]

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