import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def send_form_email(body: str) -> bool:
    """
    Send an email with form submission details.
    
    Args:
        body (str): The email body content
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    # Email details
    smtp_server = 'smtp.gmail.com'
    smtp_port = 587
    sender_email = 'ericd3770@gmail.com'
    sender_password = 'jzwrdtbufkiqdodo'
    receiver_email = 'ericd3770@gmail.com'

    subject = 'New Form Submission'

    # Set up the MIME message
    message = MIMEMultipart()
    message['From'] = sender_email
    message['To'] = receiver_email
    message['Subject'] = subject
    message.attach(MIMEText(body, 'plain'))

    try:
        # Connect to the server
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()  # Secure the connection
        server.login(sender_email, sender_password)
        
        # Send the email
        server.send_message(message)
        print('Email sent successfully!')
        return True
        
    except Exception as e:
        print(f'Error sending email: {e}')
        return False
        
    finally:
        server.quit()