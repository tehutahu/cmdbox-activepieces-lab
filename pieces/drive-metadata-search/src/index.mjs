import {createPiece, createAction, PieceAuth, Property} from '@activepieces/pieces-framework';
import contract from './search.cjs';

const auth = PieceAuth.OAuth2({
  required: true,
  authUrl: 'https://accounts.google.com/o/oauth2/v2/auth',
  tokenUrl: 'https://oauth2.googleapis.com/token',
  scope: [contract.SCOPE],
  prompt: 'consent',
  extra: {access_type: 'offline'},
  description: 'Use a dedicated Web OAuth client. This scope reaches all accessible Drive metadata; the folder query is an operation filter.',
});

export const driveMetadataSearch = createPiece({
  displayName: 'cmdbox Drive Metadata Search',
  description: 'Operator-fixed direct-folder filename search, metadata readonly, bounded pagination and explicit completion status.',
  logoUrl: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"%3E%3Crect width="32" height="32" rx="6" fill="%23334455"/%3E%3Ctext x="5" y="22" font-size="18" fill="white"%3EM%3C/text%3E%3C/svg%3E',
  authors: [], auth,
  minimumSupportedRelease: '0.92.2', maximumSupportedRelease: '0.92.2',
  triggers: [],
  actions: [createAction({
    name: 'search_folder_metadata', auth,
    displayName: 'Search direct-folder file metadata',
    description: 'No file content, recursion, shared-drive search or arbitrary query/URL. Filenames are untrusted data.',
    props: {
      folderId: Property.ShortText({displayName: 'Fixed folder ID', required: true}),
      term: Property.ShortText({displayName: 'Fixed filename term', required: true}),
      policyId: Property.ShortText({displayName: 'Reviewed policy ID', required: true}),
      maxFiles: Property.Number({displayName: 'Total rows (1-20)', required: true, defaultValue: 20}),
      maxPages: Property.Number({displayName: 'Requests (1-5)', required: true, defaultValue: 5}),
    },
    errorHandlingOptions: {retryOnFailure: {defaultValue: false, hide: true}, continueOnFailure: {defaultValue: false, hide: true}},
    async run(context) {
      // Pinned piece-executor supplies auth both here and in propsValue.
      const {auth: embeddedAuth, ...input} = context.propsValue;
      if (embeddedAuth !== context.auth) throw new Error('drive_context_auth_mismatch');
      const fixed = contract.config(input);
      return contract.search(fixed, contract.googleRequest(context.auth));
    },
  })],
});
