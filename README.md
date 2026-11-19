# Ofoq Platform

Ofoq is an Arabic-first platform with a shared account center and a dedicated learning application, Ofoq Masar. The applications share sign-in through Keycloak and keep their own application data and permissions.

## Repository layout

| Directory | Purpose | Main technology |
| --- | --- | --- |
| [ofoq-site](ofoq-site/) | Public Ofoq portal and entry point to the ecosystem | Next.js, React, Payload CMS |
| [ofoq-masar](ofoq-masar/) | Course catalog, student and instructor workspaces, assessments, and programming lab | Django, Channels, Redis |
| [ofoq-keycloak-theme](ofoq-keycloak-theme/) | Branded sign-in, registration, and account management | Keycloak, React account UI, FreeMarker |

## Learning experience

- Visitors can explore published courses, review curricula and pricing, and open public instructor profiles. Course previews expose only content marked for preview.
- Students can enroll in eligible free courses, use favorites and the cart, access their enrolled courses, and resume from the last available content item. Lessons can contain text, images, video, or downloadable files.
- Students explicitly mark content complete. Content progress is distinct from assessment results. Unit assessments require completion of their unit content. Course assessments require course content completion and submission of the required unit assessments.
- Course discussions use authenticated WebSocket connections. Lesson comments, teacher replies, course ratings, and dashboard notifications support interaction around the course.
- The programming lab offers published challenges, personal code drafts, visible examples, and asynchronous evaluation. Running an example compares its output using the challenge's configured policy. Checking a solution evaluates the full case set and records completion only when all required cases pass. Students receive aggregate results for hidden cases.

## Teaching and administration

- Instructors organize units, lessons, assessments, and course challenges in a working revision. They can preview their changes, submit them for review, and inspect revision history.
- Reviewers use Django Admin to review eligible revisions. Approval publishes a coherent revision. Restoration creates a new draft that follows the same review process. Student enrollments, existing attempts, and supported historical records are preserved across revisions.
- Instructor permissions and reviewer permissions are managed in Django. Keycloak manages identity and account sessions. Administrative and instructor access should be assigned explicitly.
- The current cart and course pricing are part of Masar. Payment processing and instructor payout should be configured and verified separately before accepting real transactions.

## Local setup

1. Clone this repository. Keep environment files, database copies, uploads, and development credentials outside Git.
2. Start Keycloak and configure a development realm. The existing local setup uses `http://localhost:8081/realms/ofoq-dev`. Register separate confidential clients for the portal and Masar. Set exact redirect and logout URLs for each application's origin and install the Ofoq theme as described in the [theme guide](ofoq-keycloak-theme/README.md).
3. For the public portal, enter `ofoq-site`, copy `.env.example` to the local environment file, and configure Payload and Keycloak using the example. Install dependencies with `pnpm install`, then run `pnpm dev`. The usual portal URL is `http://localhost:3000`.
4. For Masar, enter `ofoq-masar`, create a virtual environment using the version in `.python-version`, and install `requirements.txt`. Use [the environment example](ofoq-masar/.env.example) to configure the server. Start Redis for discussions. Run the following from `ofoq-masar/educa` with the virtual environment active, against a local development database.

   ```sh
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver localhost:8000
   ```

5. Open Masar on `http://localhost:8000`. Use that hostname consistently during OIDC login so the browser retains its session. See the [Masar Keycloak guide](ofoq-masar/KEYCLOAK.md) for client details.

## Programming lab operations

Judge0 CE runs as a separate execution service. Configure its endpoint and authentication on the server, validate supported languages, and verify runtime isolation before enabling student execution. Examples and evaluations are queued. A worker processes them independently of web requests.

```sh
python manage.py lab_run_worker --kind all
```

Use an isolated preview database for end-to-end experiments. The lab documentation covers [the data and publication model](ofoq-masar/educa/courses/LAB.md), [Judge0 setup](ofoq-masar/educa/courses/LAB_JUDGE0.md), [run queues](ofoq-masar/educa/courses/LAB_RUNS.md), [submission evaluation](ofoq-masar/educa/courses/LAB_SUBMISSIONS.md), and [editor persistence](ofoq-masar/educa/courses/LAB_EDITOR.md).

## Useful routes and checks

| Route on Masar | Purpose |
| --- | --- |
| `/courses/` | Public course discovery |
| `/cart/` | Shopping cart |
| `/students/dashboard/` | Student dashboard |
| `/students/challenges/` | Programming challenges |
| `/teachers/dashboard/` | Instructor dashboard |
| `/admin/` | Django administration and review |

From `ofoq-masar/educa`, use `python manage.py check` to inspect Django configuration and `python manage.py test courses students` for backend regression tests. Use the associated JavaScript tests for client-side controls. Keep private Judge0 credentials and evaluation data on the server, and use a separate configuration for production applications and their databases.
