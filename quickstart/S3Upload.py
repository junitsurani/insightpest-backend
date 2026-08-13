@bp.route('/interviews', methods=['POST'])
def add_interview():
    data = request.form.to_dict()
    user_id = data.get('user_id')

    if not user_id:
        print("Unauthorized: No user_id provided")
        return jsonify({"error": "Unauthorized"}), 401

    # Retrieve the person associated with the given person_id and user_id
    print(f"Fetching person with ID: {data['person_id']} and user_id: {user_id}")
    person = Person.get_by_id_and_user_id(data['person_id'], user_id)

    if not person:
        print(f"Person not found or unauthorized for ID: {data['person_id']}")
        return jsonify({"error": "Person not found or unauthorized"}), 404

    # Get the section IDs
    section_ids = request.form.getlist('section_ids[]')
    if not section_ids:
        print("No section_ids provided")
        return jsonify({"error": "At least one Section ID is required"}), 400

    # Verify all section IDs belong to the person
    for section_id in section_ids:
        section = Section.query.filter_by(id=section_id, person_id=person.id).first()
        if not section:
            print(f"Section with ID {section_id} not found for person ID {person.id}")
            return jsonify({"error": f"Section with ID {section_id} not found"}), 404

    # if 'audio_file' not in request.files:
    #     print("No audio file provided in request")
    #     return jsonify({"error": "No audio file part"}), 400
    #
    # audio_file = request.files['audio_file']
    # if audio_file.filename == '':
    #     print("No selected file for upload")
    #     return jsonify({"error": "No selected file"}), 400
    #
    #
    #
    # if audio_file:
    audio_url = None

    # Handle file upload or use existing URL
    if 'audio_file' in request.files and request.files['audio_file'].filename != '':
        audio_file = request.files['audio_file']
        filename = secure_filename(audio_file.filename)
        # filename = secure_filename(audio_file.filename)
        print(f"Uploading file: {filename} to S3")

        # Retrieve AWS credentials from environment variables
        aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
        aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        region_name = os.getenv('AWS_REGION')
        bucket_name = "aizenstorage"

        s3 = boto3.client(
            's3',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name
        )

        try:
            # Upload file to S3
            s3.upload_fileobj(audio_file, bucket_name, filename)
            audio_url = f"https://{bucket_name}.s3.{region_name}.amazonaws.com/{filename}"
            print(f"File uploaded successfully: {audio_url}")
        except Exception as e:
            print(f"Error uploading file: {e}")
            return jsonify({"error": "Failed to upload file"}), 500
    elif 'audio_url' in request.form:
        audio_url = request.form['audio_url']
        # Create a new interview instance and associate it with the selected sections
    new_interview = Interview(
        section_ids=section_ids,  # Use the list of section IDs
        interview_date=data['interview_date'],
        interviewer_name=data['interviewer_name'],
        interview_type=data['interview_type'],
        audio_file=audio_url
    )

    db.session.add(new_interview)
    db.session.commit()

    print(f"Interview added for section IDs: {section_ids}, interview ID: {new_interview.id}")
    return jsonify({"message": "Interview added", "interview_id": new_interview.id}), 201
