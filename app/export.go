// Adapted from Cosmos SDK v0.55.0 simapp; see NOTICE and LICENSE.cosmos-sdk.
package app

import (
	"encoding/json"
	"errors"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	servertypes "github.com/cosmos/cosmos-sdk/server/types"
	"github.com/cosmos/cosmos-sdk/x/staking"
)

// Export preserves the current height and validator state. Resetting validator
// signing history to height zero is deliberately outside the local operator API.
func (app *App) ExportAppStateAndValidators(forZeroHeight bool, jailAllowedAddrs, modules []string) (servertypes.ExportedApp, error) {
	if forZeroHeight || len(jailAllowedAddrs) != 0 {
		return servertypes.ExportedApp{}, errors.New("zero-height and jail-list export are not supported; use a normal snapshot")
	}
	ctx := app.NewContextLegacy(true, cmtproto.Header{Height: app.LastBlockHeight()})
	state, err := app.ModuleManager.ExportGenesisForModules(ctx, app.appCodec, modules)
	if err != nil {
		return servertypes.ExportedApp{}, err
	}
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return servertypes.ExportedApp{}, err
	}
	validators, err := staking.WriteValidators(ctx, app.StakingKeeper)
	return servertypes.ExportedApp{
		AppState: data, Validators: validators, Height: app.LastBlockHeight() + 1,
		ConsensusParams: app.GetConsensusParams(ctx),
	}, err
}
