from app import create_app
from app.models import db
from app.models.user import Story

def add_default_stories():
    app = create_app()
    with app.app_context():
        # Check if stories already exist
        if Story.query.first() is not None:
            print("Default stories already exist")
            return

        default_stories = [
            {
                'username': 'admin',  # Default admin user
                'title': 'El Perro y el Gato',
                'description': 'Una historia simple sobre la amistad entre un perro y un gato.',
                'level': 'Beginner',
                'read_time': 5,
                'content': '''Había una vez un perro llamado Max y un gato llamado Luna. Vivían en la misma casa pero no se llevaban bien.

Un día, Max encontró una pelota roja en el jardín. Comenzó a jugar con ella, pero la pelota rodó debajo del sofá donde Luna estaba durmiendo.

Luna se despertó y vio la pelota. En lugar de enojarse, se acercó a Max y comenzaron a jugar juntos. Desde ese día, Max y Luna se convirtieron en los mejores amigos.

La moraleja de la historia es que a veces las amistades más inesperadas pueden ser las más especiales.''',
                'completed': False
            },
            {
                'username': 'admin',
                'title': 'La Ciudad Misteriosa',
                'description': 'Una aventura emocionante en una ciudad llena de secretos.',
                'level': 'Intermediate',
                'read_time': 10,
                'content': '''En una ciudad antigua, María descubrió un mapa misterioso en el ático de su abuela. El mapa mostraba pasajes secretos debajo de la ciudad.

Con su amigo Carlos, decidieron explorar los túneles. Llevaban linternas y un cuaderno para anotar sus descubrimientos.

En los túneles encontraron antiguas pinturas en las paredes que contaban la historia de la ciudad. También descubrieron una cámara secreta con tesoros antiguos.

La aventura les enseñó que la historia de su ciudad era más fascinante de lo que imaginaban.''',
                'completed': False
            },
            {
                'username': 'admin',
                'title': 'El Viaje a las Estrellas',
                'description': 'Un cuento de ciencia ficción sobre un viaje interestelar.',
                'level': 'Advanced',
                'read_time': 15,
                'content': '''El Dr. Elena Martínez había dedicado su vida a la exploración espacial. Su último proyecto, la nave Estrella, estaba lista para su primer viaje interestelar.

Durante el viaje, la nave encontró una anomalía en el espacio-tiempo. Elena y su equipo descubrieron que podían ver diferentes momentos en el tiempo a través de esta ventana cósmica.

Lo que vieron les cambió la perspectiva sobre la humanidad y el universo. Comprendieron que cada decisión, por pequeña que sea, puede tener consecuencias enormes en el futuro.

Al regresar a la Tierra, Elena compartió sus descubrimientos con el mundo, inspirando a una nueva generación de exploradores espaciales.''',
                'completed': False
            }
        ]

        for story_data in default_stories:
            story = Story(**story_data)
            db.session.add(story)

        db.session.commit()
        print("Default stories added successfully")

if __name__ == '__main__':
    add_default_stories() 